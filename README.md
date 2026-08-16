# 🚗 Boaz Fleet Suite

A streamlined Streamlit application designed for automated fleet management, fuel card reconciliation, active driver compliance tracking, and GO Portal data extraction.

---

## 📌 Features

* **⛽ Fuel Reconciliation Pipeline:** Automates matching between Total Extranet statement logs (`.csv` / `.xlsx`) and internal GO Portal fuel logs, mapping missing entries directly to driver contact details.
* **📋 Fleet Login Compliance Tracker:** Analyzes vehicle activity to flag non-compliant or inactive vehicles based on configurable inactivity thresholds (in days).
* **🔍 GO Portal Web Scraper:** Built-in web scraping utility using BeautifulSoup to extract live table data across various GO Portal endpoints (`fuel`, `trips`, `vehicles`, `drivers`).

---

## 🛠️ Installation & Setup

### 1. Prerequisites
Ensure you have **Python 3.9+** installed on your system.

### 2. Clone the Repository
```bash
git clone [https://github.com/BoazOmolo/FleetApp.git]
cd FleetApp