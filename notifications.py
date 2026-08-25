import os
import re
import ssl
import smtplib
import logging
import tempfile
import mimetypes
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime
from typing import Union, List, Optional
import pandas as pd

# ==========================================
# 1. LOGGING & CONFIGURATION
# ==========================================
logger = logging.getLogger("FleetReconciliation.Notifications")

TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"
SEND_EMAILS = os.getenv("SEND_EMAILS", "True").lower() == "true"

SMTP_SERVER = os.getenv("FUEL_SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("FUEL_SMTP_PORT", 587))
EMAIL_ADDRESS = os.getenv("FUEL_SMTP_EMAIL", "fleet@davisandshirtliff.com")
EMAIL_PASSWORD = os.getenv("FUEL_SMTP_PASSWORD", "")

# Country Names Mapping
COUNTRY_NAMES = {
    "KE": "Kenya",
    "UG": "Uganda",
    "TZ": "Tanzania",
    "RW": "Rwanda",
    "SS": "South Sudan",
    "ZM": "Zambia"
}

# Dynamic Executive & Audit CC Recipients per Country
COUNTRY_EXEC_CC = {
    "KE": ["audit.ke@davisandshirtliff.com", "fleet.ke@davisandshirtliff.com"],
    "UG": ["audit.ug@davisandshirtliff.com", "fleet.ug@davisandshirtliff.com"],
    "TZ": ["audit.tz@davisandshirtliff.com", "fleet.tz@davisandshirtliff.com"],
    "RW": ["audit.rw@davisandshirtliff.com"],
    "SS": ["audit.ss@davisandshirtliff.com"],
    "ZM": ["audit.zm@davisandshirtliff.com"]
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


def split_email_addresses(value: Union[str, List[str], tuple, set, None]) -> List[str]:
    """Return a deduplicated list of valid email addresses from strings, lists, or sets."""
    if not value:
        return []
        
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
# 3. EMAIL & EXCEL GENERATORS
# ==========================================
def generate_reconciliation_excel(df: pd.DataFrame, country_code: str) -> Path:
    """Generate a clean formatted Excel report of all non-compliant transactions."""
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Fuel_Reconciliation_Report_{country_code}_{timestamp}.xlsx"

    output_path = Path(tempfile.gettempdir()) / filename

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Non-Compliant Fueling", index=False)
        worksheet = writer.sheets["Non-Compliant Fueling"]

        # Auto-adjust column widths
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = col[0].column_letter
            worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

    return output_path


def build_grouped_driver_email_body(driver_name: str, driver_no: str, rows: pd.DataFrame) -> str:
    """Build single consolidated notification per driver for unmatched transactions with aligned layout."""
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
        f"{'Date/Time':<17} | {'Vehicle':<10} | {'Station':<22} | {'Volume (L)':>10} | {'Amount':>12}",
        "-" * 80,
    ]

    for _, row in rows.iterrows():
        dt = row.get("transaction_datetime")

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

        lines.append(f"{dt_text:<17} | {reg:<10} | {station:<22} | {litres_text:>10} | {amount_text:>12}")

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
    """Build country-level summary email for executive teams using vectorized counts."""
    country_name = COUNTRY_NAMES.get(country_code, country_code)

    if not df.empty:
        driver_count = int(df["driver_no"].replace("", pd.NA).dropna().nunique()) if "driver_no" in df.columns else 0
        vehicle_count = int(df["registration"].replace("", pd.NA).dropna().nunique()) if "registration" in df.columns else 0
        transaction_count = len(df)

        if "email" in df.columns:
            valid_mask = df["email"].astype(str).str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", na=False)
            email_missing = int((~valid_mask).sum())
        else:
            email_missing = 0
    else:
        driver_count = vehicle_count = transaction_count = email_missing = 0

    return f"""Dear Team,

Please find attached the {country_name} fuel record non-compliance report for {report_date:%d %B %Y}.

Summary:
• Non-compliant transactions: {transaction_count}
• Drivers affected: {driver_count}
• Vehicles affected: {vehicle_count}
• Driver emails unavailable: {email_missing}

The attached Excel spreadsheet contains full details for all transactions recorded in the Total fuel system that could not be matched to GO App fueling records. Individual driver notifications have been consolidated to one email per driver.

Please review the attached report and follow up on any outstanding cases as appropriate.

Best regards,
Fleet Management
"""


# ==========================================
# 4. SMTP EMAIL DISPATCH ENGINE
# ==========================================
def send_email(
    recipient: Union[str, List[str]], 
    subject: str, 
    body: str, 
    cc: Union[str, List[str], None] = None, 
    attachment_path: Optional[Union[str, Path]] = None,
    attachment_data: Optional[bytes] = None,
    attachment_name: Optional[str] = None
) -> str:
    """Send email message via SMTP with support for file paths or byte buffers."""
    to_list = split_email_addresses(recipient)
    cc_list = split_email_addresses(cc)

    to_lower = {x.lower() for x in to_list}
    cc_list = [x for x in cc_list if x.lower() not in to_lower]

    if not to_list:
        raise ValueError("No valid recipient email address supplied.")

    if TEST_MODE or not SEND_EMAILS:
        logger.info(
            "TEST MODE | TO=[%s] | CC=[%s] | SUBJECT=%s | ATTACHMENT=%s",
            ", ".join(to_list),
            ", ".join(cc_list) if cc_list else "NONE",
            subject,
            attachment_name or (str(attachment_path) if attachment_path else "NONE"),
        )
        return "TEST_MODE"

    if not EMAIL_PASSWORD:
        logger.warning("FUEL_SMTP_PASSWORD missing. Operating in simulated email dispatch mode.")
        return "SIMULATED"

    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.set_content(body)

    # Attach in-memory byte buffer (e.g., from BytesIO)
    if attachment_data and attachment_name:
        ctype, encoding = mimetypes.guess_type(attachment_name)
        if ctype is None or encoding is not None:
            ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(
            attachment_data,
            maintype=maintype,
            subtype=subtype,
            filename=attachment_name
        )

    # Attach physical file from disk path
    elif attachment_path:
        attachment = Path(attachment_path)
        if not attachment.exists():
            raise FileNotFoundError(f"Email attachment not found: {attachment}")
        
        ctype, encoding = mimetypes.guess_type(str(attachment))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)

        msg.add_attachment(
            attachment.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.name,
        )

    # SMTP Execution
    all_recipients = to_list + cc_list
    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.starttls(context=context)
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg, to_addrs=all_recipients)

    return "SENT"