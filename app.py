import os
import re
import ssl
import smtplib
import logging
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime, date

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

# ==========================================
# 1. LOGGING & CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("FleetReconciliation")

# Environment & App Settings
TEST_MODE = os.getenv("TEST_MODE", "True").lower() == "true"
SEND_EMAILS = os.getenv("SEND_EMAILS", "True").lower() == "true"

SMTP_SERVER = os.getenv("FUEL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("FUEL_SMTP_PORT", 587))
EMAIL_ADDRESS = os.getenv("FUEL_SMTP_EMAIL", "fleet@davisandshirtliff.com")
EMAIL_PASSWORD = os.getenv("FUEL_SMTP_PASSWORD", "")

GO_FUEL_URL = (
    "https://app.davisandshirtliff.com/GO/fuel"
    "?start={start}&end={end}"
)

COUNTRY_NAMES = {
    "KE": "Kenya",
    "UG": "Uganda",
    "TZ": "Tanzania",
    "RW": "Rwanda",
}


# ==========================================
# 2. DATA PROCESSING & UTILITIES
# ==========================================
def normalize_text(value) -> str:
    """Clean string values and handle null representations."""
    if pd.isna(value) or value is None:
        return ""
    return str(value).strip()

def normalize_registration(value) -> str:
    """Format vehicle registration numbers by stripping whitespace."""
    text = normalize_text(value)
    return re.sub(r"\s+", "", text).upper()

def build_go_url(start_date: date, end_date: date) -> str:
    """Generate dynamic GO App fueling link for a target date range."""
    return GO_FUEL_URL.format(
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
    )

def parse_html_report(html_content: str) -> pd.DataFrame:
    """Extract fuel transaction tables from HTML exports using BeautifulSoup."""
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    if not table:
        return pd.DataFrame()

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells:
            rows.append(cells)

    df = pd.DataFrame(rows, columns=headers if headers else None)
    return df


# ==========================================
# 3. EMAIL ADDRESS PARSING & VALIDATION
# ==========================================
def valid_email(value) -> bool:
    """Verify single email string syntax."""
    value = normalize_text(value)
    if not value or value.lower() in {"nan", "none", "null"}:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value))

def split_email_addresses(value):
    """Return a deduplicated list of valid email addresses from inputs."""
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(split_email_addresses(item))
        return list(dict.fromkeys(parts))

    text = normalize_text(value)
    if not text:
        return []
    parts = [x.strip() for x in re.split(r"[;,\s]+", text) if x.strip()]
    valid = [x for x in parts if valid_email(x)]
    return list(dict.fromkeys(valid))


# ==========================================
# 4. EMAIL TEMPLATE GENERATORS
# ==========================================
def build_grouped_driver_email_body(driver_name: str, driver_no: str, rows: pd.DataFrame) -> str:
    """Build single consolidated notification per driver for unmatched transactions."""
    name = driver_name or "Driver"
    transaction_count = len(rows)

    lines = [
        f"Dear {name},",
        "",
        f"Our fuel reconciliation identified {transaction_count} fuel transaction(s) recorded in the Total fuel system but not found in the GO App Fueling records for the reporting period.",
        "",
        "Please ensure that every fuel transaction is captured in the GO App by:",
        "• Checking in on the GO App",
        "• Selecting the correct vehicle",
        "• Capturing the fuel details during fueling",
        "",
        "The transactions requiring attention are:",
        "",
        "Date/Time | Vehicle | Station | Volume | Amount",
        "-" * 78,
    ]

    for _, row in rows.iterrows():
        dt = row.get("transaction_datetime")
        dt_text = dt.strftime("%d %b %Y %H:%M") if pd.notna(dt) else "Unknown"
        reg = normalize_registration(row.get("registration", "")) or "Unknown"
        station = normalize_text(row.get("station", "")) or "Unknown"
        litres = row.get("litres")
        amount = row.get("amount")
        litres_text = f"{float(litres):.2f}" if pd.notna(litres) else "-"
        amount_text = f"{float(amount):,.2f}" if pd.notna(amount) else "-"
        lines.append(f"{dt_text} | {reg} | {station} | {litres_text} | {amount_text}")

    lines.extend([
        "",
        "Please treat this as a mandatory compliance requirement. If you experienced a technical or operational problem that prevented capture on GO App, please advise Fleet Management promptly.",
        "",
        "Thank you for your cooperation.",
        "",
        "Best regards,",
        "Fleet Management",
    ])
    return "\n".join(lines)

def build_executive_email_body(country_code: str, df: pd.DataFrame, report_date: datetime) -> str:
    """Build country-level summary email for executive teams."""
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    driver_count = int(df["driver_no"].replace("", pd.NA).dropna().nunique()) if not df.empty else 0
    vehicle_count = int(df["registration"].replace("", pd.NA).dropna().nunique()) if not df.empty else 0
    transaction_count = len(df)
    email_missing = int((~df["email"].apply(valid_email)).sum()) if not df.empty else 0

    return f"""Dear Team,

Please find attached the {country_name} fuel record non-compliance report for {report_date:%d %B %Y}.

Summary:
• Non-compliant transactions: {transaction_count}
• Drivers affected: {driver_count}
• Vehicles affected: {vehicle_count}
• Driver emails unavailable: {email_missing}

The report contains the transactions recorded in the Total fuel system that could not be confidently matched to a GO App fueling record and therefore met the notification-eligible criteria. Individual driver notifications have been consolidated to one email per driver, with the relevant department email copied where available.

Please review the attached report and follow up on any outstanding cases as appropriate.

Best regards,
Fleet Management
"""


# ==========================================
# 5. CORE SMTP DISPATCHER
# ==========================================
def send_email(recipient, subject: str, body: str, cc=None, attachment_path=None) -> str:
    """Send message or log distribution parameters if TEST_MODE is active."""
    to_list = split_email_addresses(recipient)
    cc_list = split_email_addresses(cc)

    to_lower = {x.lower() for x in to_list}
    cc_list = [x for x in cc_list if x.lower() not in to_lower]

    if not to_list:
        raise ValueError("No valid recipient email address supplied.")

    if attachment_path:
        attachment = Path(attachment_path)
        if not attachment.exists():
            raise FileNotFoundError(f"Email attachment not found: {attachment}")

    if TEST_MODE or not SEND_EMAILS:
        logger.info(
            "TEST MODE | TO=[%s] | CC=[%s] | SUBJECT=%s | ATTACHMENT=%s",
            ", ".join(to_list),
            ", ".join(cc_list) if cc_list else "NONE",
            subject,
            str(attachment_path) if attachment_path else "NONE",
        )
        return "TEST_MODE"

    if not EMAIL_PASSWORD:
        raise RuntimeError("FUEL_SMTP_PASSWORD is not loaded. Cannot send email.")

    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment_path:
        attachment = Path(attachment_path)
        data = attachment.read_bytes()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=attachment.name,
        )

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.starttls(context=context)
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

    return "SENT"


# ==========================================
# 6. STREAMLIT APPLICATION INTERFACE
# ==========================================
def main():
    st.set_page_config(page_title="Fleet Fuel Reconciliation", layout="wide")
    st.title("Fleet Fuel Reconciliation & Compliance Engine")

    # Sidebar Controls
    st.sidebar.header("Reconciliation Settings")
    country = st.sidebar.selectbox("Select Country", options=list(COUNTRY_NAMES.keys()), format_func=lambda x: COUNTRY_NAMES[x])
    date_range = st.sidebar.date_input("Date Range", [date.today(), date.today()])

    if len(date_range) == 2:
        start_date, end_date = date_range
        st.sidebar.markdown(f"**GO Fuel Link:** [Open GO App]({build_go_url(start_date, end_date)})")

    # File Upload Section
    uploaded_file = st.file_uploader("Upload Total Fuel Report (CSV, Excel, HTML)", type=["csv", "xlsx", "html"])

    if uploaded_file:
        try:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            elif uploaded_file.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded_file)
            elif uploaded_file.name.endswith(".html"):
                content = uploaded_file.read().decode("utf-8")
                df = parse_html_report(content)
            else:
                df = pd.DataFrame()

            st.subheader("Data Preview")
            st.dataframe(df.head())

            if st.button("Run Reconciliation & Notify"):
                st.info("Processing non-compliant transactions...")

                # Process Grouped Notifications
                grouped = df.groupby(["driver_no", "driver_name", "email"])
                sent_count = 0

                for (d_no, d_name, d_email), group_data in grouped:
                    if not valid_email(d_email):
                        continue
                    body = build_grouped_driver_email_body(d_name, d_no, group_data)
                    subject = f"Action Required: Unmatched Fueling Records - Driver #{d_no}"
                    send_email(recipient=d_email, subject=subject, body=body)
                    sent_count += 1

                # Send Summary Report
                exec_body = build_executive_email_body(country, df, datetime.now())
                exec_subject = f"Fuel Reconciliation Executive Summary - {COUNTRY_NAMES.get(country)}"
                send_email(
                    recipient="fleet.management@davisandshirtliff.com",
                    subject=exec_subject,
                    body=exec_body,
                    cc="audit@davisandshirtliff.com"
                )

                st.success(f"Processing complete! Sent {sent_count} driver notifications and dispatched executive summary.")

        except Exception as e:
            st.error(f"Error processing file: {str(e)}")


if __name__ == "__main__":
    main()