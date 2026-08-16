import os
import re
import smtplib
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

# ==============================================================================
# 1. STREAMLIT CONFIGURATION & SESSION STATE
# ==============================================================================
st.set_page_config(
    page_title="Boaz Fleet Suite",
    page_icon="🚗",
    layout="wide"
)

if "http_session" not in st.session_state:
    st.session_state.http_session = requests.Session()

# ==============================================================================
# 2. HELPER FUNCTIONS & PIPELINE ENGINES
# ==============================================================================
def clean_registration(reg_str):
    """Normalize vehicle registration numbers (e.g., 'KAA 123A' -> 'KAA123A')."""
    if pd.isna(reg_str):
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(reg_str).upper().strip())


def fetch_go_portal_data(endpoint: str) -> pd.DataFrame:
    """Fetch and parse HTML table data from Davis & Shirtliff GO portal endpoints."""
    url = f"https://app.davisandshirtliff.com/GO/{endpoint}"
    try:
        response = st.session_state.http_session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        table = soup.find("table")
        if not table:
            return pd.DataFrame()

        headers = [th.text.strip() for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.text.strip() for td in tr.find_all("td")]
            if cells:
                rows.append(cells)
                
        return pd.DataFrame(rows, columns=headers if headers else None)
    except Exception as e:
        st.warning(f"Unable to fetch live data from GO Portal (`/GO/{endpoint}`): {e}")
        return pd.DataFrame()


def reconcile_fuel_data(extranet_df, go_fuel_df, drivers_df=None):
    """Reconciles Extranet fuel card logs against internal GO App records."""
    results = []
    
    # Identify registration column dynamically (ensuring string conversion)
    reg_col = next((col for col in extranet_df.columns if 'reg' in str(col).lower()), extranet_df.columns[0])
    extranet_df['Clean_Reg'] = extranet_df[reg_col].apply(clean_registration)
    
    # Process GO Fuel records if available
    go_regs = set()
    if not go_fuel_df.empty:
        go_reg_col = next((col for col in go_fuel_df.columns if 'reg' in str(col).lower()), go_fuel_df.columns[0])
        go_regs = set(go_fuel_df[go_reg_col].apply(clean_registration))

    # Prepare drivers master mapping if provided
    if drivers_df is not None and not drivers_df.empty:
        d_reg_col = next((c for c in drivers_df.columns if 'veh' in str(c).lower() or 'reg' in str(c).lower()), drivers_df.columns[0])
        drivers_df['Clean_Reg'] = drivers_df[d_reg_col].apply(clean_registration)

    # Match each Extranet row
    for idx, row in extranet_df.iterrows():
        clean_reg = row['Clean_Reg']
        status = "MATCHED" if clean_reg in go_regs else "MISSING_IN_GO_APP"
        
        # Resolve Driver info
        driver_name, driver_email = "Unassigned", "N/A"
        if drivers_df is not None and not drivers_df.empty:
            match = drivers_df[drivers_df['Clean_Reg'] == clean_reg]
            if not match.empty:
                driver_name = match.iloc[0].get("Driver_Name", match.iloc[0].get("Name", "Assigned Driver"))
                driver_email = match.iloc[0].get("Email", "N/A")

        results.append({
            "Registration": row[reg_col],
            "Date": row.get("Date", "N/A"),
            "Amount": row.get("Amount", "N/A"),
            "Volume_Ltrs": row.get("Volume", "N/A"),
            "Status": status,
            "Assigned_Driver": driver_name,
            "Driver_Email": driver_email
        })
        
    return pd.DataFrame(results)


def evaluate_fleet_compliance(go_trips_df, days_threshold=3):
    """Processes GO trip logs to flag vehicles missing logins exceeding threshold."""
    if go_trips_df.empty:
        return pd.DataFrame()

    # Clean duplicate column names
    cols = []
    count = {}
    for col in go_trips_df.columns:
        if col in count:
            count[col] += 1
            cols.append(f"{col}_{count[col]}")
        else:
            count[col] = 1
            cols.append(col)
    go_trips_df.columns = cols

    reg_col = go_trips_df.columns[0]
    go_trips_df['Clean_Reg'] = go_trips_df[reg_col].apply(clean_registration)
    
    summary = go_trips_df.groupby('Clean_Reg').size().reset_index(name='Total_Trips_Recorded')
    summary['Compliance_Status'] = summary['Total_Trips_Recorded'].apply(
        lambda x: 'COMPLIANT' if x >= days_threshold else 'NON_COMPLIANT'
    )
    return summary


# ==============================================================================
# 3. APPLICATION UI LAYOUT
# ==============================================================================
st.title("🚗 Boaz Fleet Suite")

# Sidebar
st.sidebar.title("⚙️ Operations Panel")
test_mode = st.sidebar.toggle("Enable Test Mode (No Emails)", value=True)
st.sidebar.markdown("---")
st.sidebar.caption("Automated Fleet Reconciliation & Compliance System")

# Navigation Tabs
tab1, tab2, tab3 = st.tabs([
    "⛽ Fuel Reconciliation", 
    "📋 Fleet Login Compliance", 
    "🔍 Web Scraper Utility"
])

# ------------------------------------------------------------------------------
# TAB 1: FUEL RECONCILIATION
# ------------------------------------------------------------------------------
with tab1:
    st.header("Fuel Card vs. GO App Reconciliation")
    
    col1, col2 = st.columns(2)
    with col1:
        extranet_file = st.file_uploader("Upload Total Extranet Statement (.csv / .xlsx)", type=["csv", "xlsx"])
    with col2:
        drivers_file = st.file_uploader("Upload Drivers Master File (.csv / .xlsx)", type=["csv", "xlsx"], key="tab1_drivers")

    tolerance_mins = st.slider("Time Window Matching Tolerance (Minutes):", 15, 180, 60)

    if st.button("Run Fuel Reconciliation Pipeline", type="primary"):
        if not extranet_file:
            st.error("Please upload a Total Extranet statement CSV or Excel file.")
        else:
            with st.spinner("Executing reconciliation matching algorithm..."):
                # Read Extranet File (.csv or .xlsx)
                extranet_df = pd.read_csv(extranet_file) if extranet_file.name.endswith(".csv") else pd.read_excel(extranet_file)
                
                # Read Drivers Master File (.csv or .xlsx)
                drivers_df = None
                if drivers_file:
                    drivers_df = pd.read_csv(drivers_file) if drivers_file.name.endswith(".csv") else pd.read_excel(drivers_file)
                
                # Fetch online portal logs
                go_fuel_df = fetch_go_portal_data("fuel")
                
                # Run matching logic
                reconciled_df = reconcile_fuel_data(extranet_df, go_fuel_df, drivers_df)
                
                # Render Metrics
                total_tx = len(reconciled_df)
                missing_tx = len(reconciled_df[reconciled_df['Status'] == 'MISSING_IN_GO_APP'])
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Transactions", total_tx)
                m2.metric("Matched in GO App", total_tx - missing_tx)
                m3.metric("Missing Entries (Non-Compliant)", missing_tx, delta_color="inverse")
                
                st.subheader("Reconciliation Results Breakdown")
                st.dataframe(reconciled_df, use_container_width=True)
                
                # Download CSV
                csv_data = reconciled_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Master Reconciliation Report (CSV)",
                    data=csv_data,
                    file_name=f"Fuel_Reconciliation_Report_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )

# ------------------------------------------------------------------------------
# TAB 2: FLEET LOGIN COMPLIANCE
# ------------------------------------------------------------------------------
with tab2:
    st.header("Fleet Active Log Tracker")
    
    c1, c2 = st.columns(2)
    with c1:
        days = st.number_input("Flag vehicles inactive for more than (days):", 1, 14, 3)
    with c2:
        regions = st.multiselect("Target Regions:", ["Kenya", "Uganda", "Tanzania", "Zambia"], default=["Kenya", "Uganda"])

    if st.button("Analyze Fleet Compliance", type="primary"):
        with st.spinner("Fetching trip logs and evaluating driver activity..."):
            go_trips_df = fetch_go_portal_data("trips")
            
            if go_trips_df.empty:
                st.info("GO Portal offline or no trip data returned. Displaying demo compliance structure.")
                demo_data = pd.DataFrame({
                    "Registration": ["KAA 123A", "KBB 456B", "KCC 789C"],
                    "Total_Trips_Recorded": [5, 1, 0],
                    "Compliance_Status": ["COMPLIANT", "NON_COMPLIANT", "NON_COMPLIANT"]
                })
                st.dataframe(demo_data, use_container_width=True)
            else:
                compliance_df = evaluate_fleet_compliance(go_trips_df, days_threshold=days)
                st.subheader("Vehicle Compliance Summary")
                st.dataframe(compliance_df, use_container_width=True)

# ------------------------------------------------------------------------------
# TAB 3: SCRAPER UTILITY
# ------------------------------------------------------------------------------
with tab3:
    st.header("GO Portal Raw Data Scraper")
    endpoint = st.selectbox("Select Endpoint:", ["fuel", "trips", "vehicles", "drivers"])
    
    if st.button("Fetch Raw Endpoint Data"):
        with st.spinner(f"Scraping endpoint `/GO/{endpoint}`..."):
            df = fetch_go_portal_data(endpoint)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
            else:
                st.error(f"No records found or endpoint `/GO/{endpoint}` was unreachable.")