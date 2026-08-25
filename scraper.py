import io
import logging
import requests
from bs4 import BeautifulSoup
import pandas as pd

logger = logging.getLogger("FleetReconciliation.Scraper")


def fetch_go_fuel_html(go_url: str, session: requests.Session = None, cookies: dict = None) -> str:
    """Fetch raw HTML contents from the GO App portal using a session or standard request."""
    try:
        client = session if session else requests
        response = client.get(go_url, cookies=cookies, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error("Failed to fetch GO Fuel data from %s: %s", go_url, str(e))
        return ""


def parse_html_report(html_content: str) -> pd.DataFrame:
    """Extract fuel transaction tables from HTML exports cleanly with pandas / BeautifulSoup fallback."""
    if not html_content or not html_content.strip():
        return pd.DataFrame()

    # Fast path: Try pandas native HTML reader
    try:
        tables = pd.read_html(io.StringIO(html_content))
        if tables:
            return tables[0]
    except Exception as e:
        logger.warning("Pandas read_html failed, falling back to manual BeautifulSoup parsing: %s", e)

    # Fallback path: Explicit BeautifulSoup parsing with column length protection
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

    if headers and rows:
        num_cols = len(headers)
        # Pad or truncate rows to ensure matching header length
        adjusted_rows = [r[:num_cols] + [""] * max(0, num_cols - len(r)) for r in rows]
        return pd.DataFrame(adjusted_rows, columns=headers)

    return pd.DataFrame(rows)