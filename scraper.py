import io
import logging
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pandas as pd

logger = logging.getLogger("FleetReconciliation.Scraper")

# Configuration Constants
MATCH_TIME_TOLERANCE_MINUTES = 30
FALLBACK_TIME_TOLERANCE_MINUTES = 120
MIN_MATCH_SCORE = 60


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

    try:
        tables = pd.read_html(io.StringIO(html_content))
        if tables:
            return tables[0]
    except Exception as e:
        logger.warning("Pandas read_html failed, falling back to manual BeautifulSoup parsing: %s", e)

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
        adjusted_rows = [r[:num_cols] + [""] * max(0, num_cols - len(r)) for r in rows]
        return pd.DataFrame(adjusted_rows, columns=headers)

    return pd.DataFrame(rows)


# ==========================================
# RECONCILIATION & SCORING UTILITIES
# ==========================================

def _amount_match(amt1: float, amt2: float, tolerance: float = 10.0) -> bool:
    """Check if transaction amounts match within a given monetary tolerance."""
    try:
        return abs(float(amt1) - float(amt2)) <= tolerance
    except (ValueError, TypeError):
        return False


def _volume_match(vol1: float, vol2: float, tolerance: float = 1.0) -> bool:
    """Check if fuel volumes match within a given litre tolerance."""
    try:
        return abs(float(vol1) - float(vol2)) <= tolerance
    except (ValueError, TypeError):
        return False


def candidate_score(total_row: pd.Series, go_row: pd.Series) -> tuple[int, dict]:
    """Calculate match confidence score between Total Extranet and GO App fueling records."""
    t_time = total_row.get("transaction_datetime")
    g_time = go_row.get("transaction_datetime")

    minutes = float("inf")
    date_match = False

    if pd.notna(t_time) and pd.notna(g_time):
        try:
            t_dt = pd.to_datetime(t_time)
            g_dt = pd.to_datetime(g_time)
            minutes = abs((t_dt - g_dt).total_seconds()) / 60.0
            date_match = t_dt.date() == g_dt.date()
        except Exception:
            pass

    amount_match = _amount_match(total_row.get("amount", 0), go_row.get("amount", 0))
    volume_match = _volume_match(total_row.get("litres", 0), go_row.get("litres", 0))

    t_station = str(total_row.get("station", "")).strip().lower()
    g_station = str(go_row.get("station", "")).strip().lower()
    station_match = bool(t_station and g_station and (t_station in g_station or g_station in t_station))

    score = 0
    if date_match:
        score += 40
    if minutes <= MATCH_TIME_TOLERANCE_MINUTES:
        score += 30
    elif minutes <= FALLBACK_TIME_TOLERANCE_MINUTES:
        score += 15

    if amount_match:
        score += 20
    if volume_match:
        score += 10
    if station_match:
        score += 10

    diag = {
        "time_diff_minutes": minutes,
        "amount_match": amount_match,
        "volume_match": volume_match,
        "date_match": date_match,
        "station_match": station_match,
    }

    return score, diag


def reconcile_fleet_data(total_df: pd.DataFrame, go_df: pd.DataFrame) -> pd.DataFrame:
    """Compare Total Extranet records with GO App entries and isolate non-compliant records."""
    if go_df.empty:
        df_out = total_df.copy()
        df_out["reconciliation_status"] = "NON_COMPLIANT"
        return df_out

    results = []
    
    # Normalize registrations for exact grouping
    if "registration" in total_df.columns:
        total_df["norm_reg"] = total_df["registration"].astype(str).str.replace(r"\s+", "", regex=True).str.upper()
    else:
        total_df["norm_reg"] = ""

    if "registration" in go_df.columns:
        go_df["norm_reg"] = go_df["registration"].astype(str).str.replace(r"\s+", "", regex=True).str.upper()
        go_by_reg = go_df.groupby("norm_reg")
    else:
        go_by_reg = None

    for _, t_row in total_df.iterrows():
        reg = t_row["norm_reg"]
        best_match = None
        best_score = -1

        if go_by_reg and reg in go_by_reg.groups:
            candidates = go_by_reg.get_group(reg)
            for _, g_row in candidates.iterrows():
                score, _ = candidate_score(t_row, g_row)
                if score > best_score:
                    best_score = score
                    best_match = g_row

        record = t_row.to_dict()
        if best_score >= MIN_MATCH_SCORE and best_match is not None:
            record["reconciliation_status"] = "MATCHED"
            record["match_score"] = best_score
        else:
            record["reconciliation_status"] = "NON_COMPLIANT"
            record["match_score"] = max(best_score, 0)

        results.append(record)

    out_df = pd.DataFrame(results)
    if "norm_reg" in out_df.columns:
        out_df.drop(columns=["norm_reg"], inplace=True)
    return out_df