import os
import re
import ssl
import smtplib
import logging
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime
import pandas as pd

# ==========================================
# 1. LOGGING & CONFIGURATION
# ==========================================
logger = logging.getLogger("FleetReconciliation.Notifications")

TEST_MODE = os.getenv("TEST_MODE", "True").lower() == "true"
SEND_EMAILS = os.getenv("SEND_EMAILS", "True").lower() == "true"

SMTP_SERVER = os.getenv("FUEL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("FUEL_SMTP_PORT", 587))
EMAIL_ADDRESS = os.getenv("FUEL_SMTP_EMAIL", "fleet@davisandshirtliff.com")
EMAIL_PASSWORD = os.getenv("FUEL_SMTP_PASSWORD", "")

COUNTRY_NAMES = {
    "KE": "Kenya",
    "UG": "Uganda",
    "TZ": "Tanzania",
    "RW": "Rwanda",
}


# ==========================================
# 2. STRING & EMAIL NORMALIZATION UTILITIES
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


def valid_email(value) -> bool:
    """Verify single email string syntax."""
    val = normalize_text(value)
    if not val or val.lower() in {"nan", "none", "null"}:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", val))


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
# 3. EMAIL TEMPLATE GENERATORS
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

        # Safely format whether dt is a Pandas Timestamp, Python datetime, or String
        if pd.notna(dt) and dt != "":
            if hasattr(dt, "strftime"):
                dt_text = dt.strftime("%d %b %Y %H:%M")
            else:
                dt_text = str(dt)
        else:
            dt_text = "Unknown"

        reg = normalize_registration(row.get("registration", "")) or "Unknown"
        station = normalize_text(row.get("station", "")) or "Unknown"
        litres = row.get("litres")
        amount = row.get("amount")

        litres_text = f"{float(litres):.2f}" if pd.notna(litres) and litres != "" else "-"
        amount_text = f"{float(amount):,.2f}" if pd.notna(amount) and amount != "" else "-"

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
    driver_count = int(df["driver_no"].replace("", pd.NA).dropna().nunique()) if not df.empty and "driver_no" in df.columns else 0
    vehicle_count = int(df["registration"].replace("", pd.NA).dropna().nunique()) if not df.empty and "registration" in df.columns else 0
    transaction_count = len(df)
    email_missing = int((~df["email"].apply(valid_email)).sum()) if not df.empty and "email" in df.columns else 0

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
# 4. SMTP EMAIL DISPATCH ENGINE
# ==========================================
def send_email(recipient, subject: str, body: str, cc=None, attachment_path=None) -> str:
    """Send email message via SMTP or log distribution parameters in TEST_MODE."""
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
        raise RuntimeError("FUEL_SMTP_PASSWORD environment variable is not loaded. Cannot dispatch emails.")

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