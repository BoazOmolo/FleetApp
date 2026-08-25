# 🚗 Boaz Fleet Suite

A clean Streamlit app built to enable automated fleet management, fuel card reconciliations, compliance tracking of active drivers, and data extraction from the GO Portal.

---

## 📌 Features

* **⛽ Fuel Reconciliation Pipeline:** 
Automatically matches Total Extranet statement logs (`.csv` / `.xlsx`) with internal GO Portal fuel logs and maps the unmatched entries to driver contacts.
* **📋 Fleet Login Compliance Tracker:** 
Vehicle Activity Analysis to identify non-compliance/inactive vehicles by using configurable inactivity days.
* **🔍 GO Portal Web Scraper:** 
An embedded web scraper using BeautifulSoup to extract live table data from GO Portal end-points (`fuel`, `trips`, `vehicles`, `drivers`).

---

## 🛠️ Installation & Setup

### 1. Prerequisites
Ensure you have **Python 3.9+** installed in your environment.

### 2. Clone the Repository
git clone [https://github.com/BoazOmolo/FleetApp.git]
cd FleetApp

### 3. Install Dependencies 
Install all required libraries using requirements.txt:

pip install -r requirements.txt