import logging
import requests
from bs4 import BeautifulSoup
import pandas as pd

logger = logging.getLogger("FleetReconciliation.Scraper")

def fetch_go_fuel_html(go_url: str, cookies: dict = None) -> str:
    """Fetch raw HTML contents from the GO App portal."""
    try:
        response = requests.get(go_url, cookies=cookies, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error("Failed to fetch GO Fuel data: %s", str(e))
        return ""

def parse_html_report(html_content: str) -> pd.DataFrame:
    """Extract fuel transaction tables from HTML exports using BeautifulSoup."""
    if not html_content:
        return pd.DataFrame()
        
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    if not table:
        return pd.DataFrame()

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells:
            rows.append(cells)

    return pd.DataFrame(rows, columns=headers if headers else None)