import os
import re
import ssl
import smtplib
import logging
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime
import pandas as pd

logger = logging.getLogger("FleetReconciliation.Notifications")

TEST_MODE = os.getenv("TEST_MODE", "True").lower() == "true"
SEND_EMAILS = os.getenv("SEND_EMAILS", "True").lower() == "true"
SMTP_SERVER = os.getenv("FUEL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("FUEL_SMTP_PORT", 587))
EMAIL_ADDRESS = os.getenv("FUEL_SMTP_EMAIL", "fleet@davisandshirtliff.com")
EMAIL_PASSWORD = os.getenv("FUEL_SMTP_PASSWORD", "")

COUNTRY_NAMES = {"KE": "Kenya", "UG": "Uganda", "TZ": "Tanzania", "RW": "Rwanda"}

def normalize_text(value) -> str:
    if pd.isna(value) or value is None:
        return ""
    return str(value).strip()

def normalize_registration(value) -> str:
    return re.sub(r"\s+", "", normalize_text(value)).upper()

def valid_email(value) -> bool:
    val = normalize_text(value)
    if not val or val.lower() in {"nan", "none", "null"}:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", val))

def split_email_addresses(value):
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(split_email_addresses(item))
        return list(dict.fromkeys(parts))
    text = normalize_text(value)
    if not text:
        return []
    parts = [x.strip() for x in re.split(r"[;,\s]+", text) if x.strip()]
    return list(dict.fromkeys([x for x in parts if valid_email(x)]))

def build_grouped_driver_email_body(driver_name: str, driver_no: str, rows: pd.DataFrame) -> str:
    name = driver_name or "Driver"
    lines = [
        f"Dear {name},",
        "",
        f"Our fuel reconciliation identified {len(rows)} fuel transaction(s) recorded in the Total fuel system but not found in the GO App Fueling records.",
        "",
        "Please ensure that every fuel transaction is captured in the GO App.",
        "",
        "Date/Time | Vehicle | Station | Volume | Amount",
        "-" * 78,
    ]
    for _, row in rows.iterrows():
        dt = row.get("transaction_datetime")
        dt_text = dt.strftime("%d %b %Y %H:%M") if pd.notna(dt) else "Unknown"
        reg = normalize_registration(row.get("registration", "")) or "Unknown"
        station = normalize_text(row.get("station", "")) or "Unknown"
        litres = f"{float(row.get('litres')):.2f}" if pd.notna(row.get("litres")) else "-"
        amount = f"{float(row.get('amount')):,.2f}" if pd.notna(row.get("amount")) else "-"
        lines.append(f"{dt_text} | {reg} | {station} | {litres} | {amount}")

    lines.extend(["", "Best regards,", "Fleet Management"])
    return "\n".join(lines)

def build_executive_email_body(country_code: str, df: pd.DataFrame, report_date: datetime) -> str:
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    return f"""Dear Team,

Please find attached the {country_name} fuel record non-compliance report for {report_date:%d %B %Y}.

Summary:
• Non-compliant transactions: {len(df)}
• Drivers affected: {int(df['driver_no'].replace('', pd.NA).dropna().nunique()) if not df.empty else 0}
• Vehicles affected: {int(df['registration'].replace('', pd.NA).dropna().nunique()) if not df.empty else 0}

Best regards,
Fleet Management"""

def send_email(recipient, subject: str, body: str, cc=None, attachment_path=None) -> str:
    to_list = split_email_addresses(recipient)
    cc_list = [x for x in split_email_addresses(cc) if x.lower() not in {y.lower() for y in to_list}]

    if not to_list:
        raise ValueError("No valid recipient email address supplied.")

    if TEST_MODE or not SEND_EMAILS:
        logger.info("TEST MODE | TO=[%s] | SUBJECT=%s", ", ".join(to_list), subject)
        return "TEST_MODE"

    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.starttls(context=context)
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

    return "SENT"