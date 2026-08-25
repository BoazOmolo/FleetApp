import csv
import logging
from datetime import datetime
from pathlib import Path
import streamlit as st

LOG_FILE = Path("app_audit_log.csv")

# Ensure CSV audit log exists with headers
if not LOG_FILE.exists():
    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "user_email", "country", "action", "details"])

def get_current_user_email() -> str:
    """Retrieve authenticated email via Streamlit OIDC or session state fallback."""
    if hasattr(st, "user") and getattr(st.user, "is_logged_in", False):
        return st.user.get("email", "authenticated_user")
    return st.session_state.get("active_user_email", "")

def log_audit_event(action: str, country: str, details: str = ""):
    """Log user actions to both the audit CSV file and system logger."""
    user_email = get_current_user_email() or "anonymous_user"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Append to CSV log file
    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, user_email, country, action, details])

    # Log to standard output
    logging.info(f"AUDIT | User: {user_email} | Country: {country} | Action: {action} | Details: {details}")