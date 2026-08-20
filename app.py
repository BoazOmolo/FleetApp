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

GO_FUEL_URL = "https://app.davisandshirtliff.com/GO/fuel?start={start}&end={end}"

def build_go_url(start_date: date, end_date: date) -> str:
    return GO_FUEL_URL.format(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

def main():
    st.set_page_config(page_title="Fleet Fuel Reconciliation", layout="wide")
    st.title("Fleet Fuel Reconciliation & Compliance Engine")

    st.sidebar.header("Reconciliation Settings")
    country = st.sidebar.selectbox("Select Country", options=list(COUNTRY_NAMES.keys()), format_func=lambda x: COUNTRY_NAMES[x])
    date_range = st.sidebar.date_input("Date Range", [date.today(), date.today()])

    if len(date_range) == 2:
        st.sidebar.markdown(f"**GO Fuel Link:** [Open GO App]({build_go_url(date_range[0], date_range[1])})")

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

            st.subheader("Data Preview")
            st.dataframe(df.head())

            if st.button("Run Reconciliation & Notify"):
                grouped = df.groupby(["driver_no", "driver_name", "email"])
                sent_count = 0

                for (d_no, d_name, d_email), group_data in grouped:
                    if not valid_email(d_email):
                        continue
                    body = build_grouped_driver_email_body(d_name, d_no, group_data)
                    send_email(recipient=d_email, subject=f"Action Required: Unmatched Fueling Records - Driver #{d_no}", body=body)
                    sent_count += 1

                exec_body = build_executive_email_body(country, df, datetime.now())
                send_email(
                    recipient="fleet.management@davisandshirtliff.com",
                    subject=f"Fuel Reconciliation Executive Summary - {COUNTRY_NAMES.get(country)}",
                    body=exec_body,
                    cc="audit@davisandshirtliff.com"
                )

                st.success(f"Processing complete! Sent {sent_count} notifications.")

        except Exception as e:
            st.error(f"Error processing file: {str(e)}")

if __name__ == "__main__":
    main()