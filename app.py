from datetime import date, datetime
import pandas as pd
import streamlit as st

from scraper import parse_html_report
from notifications import (
    COUNTRY_NAMES,
    valid_email,
    build_grouped_driver_email_body,
    build_executive_email_body,
    send_email,
)

# Configuration & Assets
GO_FUEL_URL = "https://app.davisandshirtliff.com/GO/fuel?start={start}&end={end}"
DS_LOGO_URL = "https://www.davisandshirtliff.com/images/ds-logo.png"

def build_go_url(start_date: date, end_date: date) -> str:
    return GO_FUEL_URL.format(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

def inject_custom_styles():
    """Inject Davis & Shirtliff custom brand styling."""
    st.markdown(
        """
        <style>
            /* Main header styling */
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
            /* Custom card container */
            .ds-card {
                background-color: #FFFFFF;
                border-left: 5px solid #D32F2F;
                padding: 15px 20px;
                border-radius: 4px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            /* Primary button hover effects */
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
        page_icon="⛽",
        layout="wide",
    )
    
    inject_custom_styles()

    # Sidebar Header & Branding
    st.sidebar.image(DS_LOGO_URL, use_container_width=True)
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

    # Main Screen Title Section
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image(DS_LOGO_URL, width=140)
    with col2:
        st.markdown("<h1 class='main-title'>Davis & Shirtliff</h1>", unsafe_allow_html=True)
        st.markdown("<div class='sub-title'>Fleet Fuel Reconciliation & Compliance Engine</div>", unsafe_allow_html=True)

    st.markdown("---")

    # Upload & Reconciliation Interface
    st.markdown("<div class='ds-card'><b>Data Ingestion:</b> Upload Total Fuel system export files (CSV, XLSX, HTML) to reconcile against GO App records.</div>", unsafe_allow_html=True)
    
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
                grouped = df.groupby(["driver_no", "driver_name", "email"])
                sent_count = 0

                for (d_no, d_name, d_email), group_data in grouped:
                    if not valid_email(d_email):
                        continue
                    body = build_grouped_driver_email_body(d_name, d_no, group_data)
                    send_email(
                        recipient=d_email, 
                        subject=f"Davis & Shirtliff | Action Required: Unmatched Fueling Records (Driver #{d_no})", 
                        body=body
                    )
                    sent_count += 1

                exec_body = build_executive_email_body(country, df, datetime.now())
                send_email(
                    recipient="fleet.management@davisandshirtliff.com",
                    subject=f"Davis & Shirtliff | Fuel Reconciliation Executive Summary - {COUNTRY_NAMES.get(country)}",
                    body=exec_body,
                    cc="audit@davisandshirtliff.com"
                )

                st.success(f"Reconciliation completed successfully. Dispatched {sent_count} driver compliance emails and delivered the executive report.")

        except Exception as e:
            st.error(f"Error processing upload: {str(e)}")

if __name__ == "__main__":
    main()