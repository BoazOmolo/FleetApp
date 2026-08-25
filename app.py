from datetime import date, datetime
from pathlib import Path
import pandas as pd
import streamlit as st

from scraper import parse_html_report
from notifications import (
    COUNTRY_NAMES,
    COUNTRY_EXEC_CC,
    TEST_MODE,
    valid_email,
    build_grouped_driver_email_body,
    build_executive_email_body,
    generate_reconciliation_excel,
    send_email,
)

# Configuration & Branding Assets
GO_FUEL_URL = "https://app.davisandshirtliff.com/GO/fuel?start={start}&end={end}"
DIRECT_LOGO_URL = "https://www.davisandshirtliff.com/images/dslogo.png"
LOCAL_LOGO_PATH = Path("assets/dslogo.png")


def get_logo_source():
    """Return local image path if present, otherwise default to direct URL."""
    if LOCAL_LOGO_PATH.exists():
        return str(LOCAL_LOGO_PATH)
    return DIRECT_LOGO_URL


def build_go_url(start_date: date, end_date: date) -> str:
    return GO_FUEL_URL.format(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))


def inject_custom_styles():
    """Inject Davis & Shirtliff custom brand styling and hide toolbar items."""
    st.markdown(
        """
        <style>
            [data-testid="stHeaderActionElements"], .stAppToolbar, #MainMenu, footer {
                display: none !important;
                visibility: hidden !important;
            }
            .main-title {
                color: #D32F2F;
                font-weight: 700;
                margin-bottom: 0px;
            }
            .sub-title {
                color: #64748B;
                font-size: 1.1rem;
                margin-bottom: 25px;
            }
            .ds-card {
                background-color: #FFFFFF;
                border-left: 5px solid #D32F2F;
                padding: 15px 20px;
                border-radius: 4px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            .stButton>button {
                border-radius: 4px;
                font-weight: 600;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(
        page_title="Davis & Shirtliff - Fuel Reconciliation Engine",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'Get Help': None,
            'Report a bug': None,
            'About': None
        }
    )

    inject_custom_styles()
    logo_src = get_logo_source()

    # Sidebar Header & Branding
    st.sidebar.image(logo_src, use_container_width=True)
    st.sidebar.markdown("---")
    st.sidebar.header("Reconciliation Settings")

    country = st.sidebar.selectbox(
        "Select Country",
        options=list(COUNTRY_NAMES.keys()),
        format_func=lambda x: COUNTRY_NAMES[x]
    )

    date_range = st.sidebar.date_input("Date Range", [date.today(), date.today()])

    if len(date_range) == 2:
        st.sidebar.markdown(f"**GO Fuel Portal:** [Open GO App]({build_go_url(date_range[0], date_range[1])})")

    # Mode Status Indicator
    if TEST_MODE:
        st.sidebar.warning("⚠️ **TEST MODE ENABLED**\nEmails will be logged to console instead of live dispatch.")
    else:
        st.sidebar.success("🚀 **LIVE MODE ENABLED**\nEmails will be dispatched to drivers.")

    # Main Header Section
    st.markdown("<h1 class='main-title'>Davis & Shirtliff</h1>", unsafe_allow_html=True)
    st.markdown("<div class='sub-title'>Fleet Fuel Reconciliation & Compliance Engine</div>", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown(
        "<div class='ds-card'><b>Data Ingestion:</b> Upload Total Fuel system export files (CSV, XLSX, HTML) to reconcile against GO App records.</div>",
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader("Upload Total Fuel Report", type=["csv", "xlsx", "html"])

    if uploaded_file:
        try:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            elif uploaded_file.name.endswith(".xlsx"):
                df = pd.read_excel(uploaded_file)
            elif uploaded_file.name.endswith(".html"):
                df = parse_html_report(uploaded_file.read().decode("utf-8"))
            else:
                df = pd.DataFrame()

            st.subheader("Transaction Data Preview")
            st.dataframe(df.head(), use_container_width=True)

            if st.button("Run Reconciliation & Send Notifications", type="primary"):
                # Column validation check
                required_cols = {"driver_no", "driver_name", "email"}
                missing_cols = required_cols - set(df.columns)
                if missing_cols:
                    st.error(f"Upload error: Missing required column(s): {', '.join(missing_cols)}")
                    st.stop()

                # Clean missing fields to preserve group integrity without dropping rows
                df_clean = df.copy()
                df_clean[["driver_no", "driver_name", "email"]] = df_clean[["driver_no", "driver_name", "email"]].fillna("")

                grouped = list(df_clean.groupby(["driver_no", "driver_name", "email"], dropna=False))
                sent_count = 0
                progress_bar = st.progress(0)

                # 1. Dispatch consolidated driver notifications
                for idx, ((d_no, d_name, d_email), group_data) in enumerate(grouped):
                    if valid_email(d_email):
                        body = build_grouped_driver_email_body(d_name, d_no, group_data)
                        send_email(
                            recipient=d_email,
                            subject=f"Davis & Shirtliff | Action Required: Unmatched Fueling Records (Driver #{d_no})",
                            body=body
                        )
                        sent_count += 1
                    progress_bar.progress((idx + 1) / len(grouped))

                # 2. Generate detailed Excel audit sheet
                excel_report_path = generate_reconciliation_excel(df, country)

                # 3. Dynamic CC list mapping from selected country
                exec_cc_recipients = COUNTRY_EXEC_CC.get(country, [])

                # 4. Deliver Executive Summary with Excel Attachment & Dynamic CCs
                exec_body = build_executive_email_body(country, df, datetime.now())
                send_email(
                    recipient="boazomolo14@gmail.com",
                    subject=f"Davis & Shirtliff | Daily Fuel Reconciliation Audit Report - {COUNTRY_NAMES.get(country, country)}",
                    body=exec_body,
                    cc=exec_cc_recipients,
                    attachment_path=str(excel_report_path)
                )

                st.success(
                    f"Reconciliation completed successfully! Dispatched {sent_count} driver compliance emails "
                    f"and delivered the full Excel audit report to boazomolo14@gmail.com."
                )

        except Exception as e:
            st.error(f"Error processing upload: {str(e)}")


if __name__ == "__main__":
    main()