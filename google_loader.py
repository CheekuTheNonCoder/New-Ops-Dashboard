"""
google_loader.py — Production-grade Google Sheets Ingestion & Sync Engine (v4.0)
Connects directly to spreadsheet ID with exponential backoff and dual-access pathways.
"""
import io
import json
import time
import urllib.request
import pandas as pd
import streamlit as st

# Safe import checking for Google Sheet API drivers
try:
    import gspread
    from google.oauth2.service_account import Credentials
    from gspread_dataframe import get_as_dataframe
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

SPREADSHEET_ID = "1h1464iaglel2B-oQbY9kuNkL7_yZYHKqEACxIDg_rxg"


def get_gcp_credentials():
    """Retrieves Google service account credentials cleanly from Streamlit Secrets."""
    if "gcp_service_account" in st.secrets:
        try:
            info = dict(st.secrets["gcp_service_account"])
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
            return Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
            )
        except Exception as e:
            st.sidebar.warning(f"⚠️ Credentials parsing failed: {e}")
    return None


@st.cache_data(ttl=600, show_spinner=False)
def load_sheet_data(sheet_id: str = SPREADSHEET_ID, max_retries: int = 3, backoff_factor: float = 1.5):
    """
    Downloads worksheets 'Delivered' and 'Tickets' from the specified Google Sheet.
    Utilizes authenticated API connections, falling back gracefully to public CSV exports.
    """
    errs = []

    # Method 1: Authenticated API Connection
    if HAS_GSPREAD:
        creds = get_gcp_credentials()
        if creds:
            for attempt in range(max_retries):
                try:
                    client = gspread.authorize(creds)
                    sheet = client.open_by_key(sheet_id)
                    
                    # Read 'Delivered' worksheet
                    del_ws = sheet.worksheet("Delivered")
                    del_df = get_as_dataframe(del_ws, evaluate_formulas=True, fill_value=None)
                    del_df = del_df.dropna(how="all").dropna(axis=1, how="all")
                    
                    # Read 'Tickets' worksheet
                    tick_ws = sheet.worksheet("Tickets")
                    tick_df = get_as_dataframe(tick_ws, evaluate_formulas=True, fill_value=None)
                    tick_df = tick_df.dropna(how="all").dropna(axis=1, how="all")
                    
                    return del_df, tick_df
                except Exception as e:
                    errs.append(f"Authenticated GSpread Attempt {attempt+1} failed: {str(e)}")
                    time.sleep(backoff_factor ** attempt)

    # Method 2: Public URL Export Fallback
    for attempt in range(max_retries):
        try:
            del_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Delivered"
            tick_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Tickets"
            
            headers = {"User-Agent": "Mozilla/5.0 (OpsIntelPlatform v4.0)"}
            
            # Fetch Delivered CSV stream
            req_del = urllib.request.Request(del_url, headers=headers)
            with urllib.request.urlopen(req_del, timeout=12) as r:
                del_df = pd.read_csv(io.BytesIO(r.read()))
                
            # Fetch Tickets CSV stream
            req_tick = urllib.request.Request(tick_url, headers=headers)
            with urllib.request.urlopen(req_tick, timeout=12) as r:
                tick_df = pd.read_csv(io.BytesIO(r.read()))
                
            del_df = del_df.dropna(how="all")
            tick_df = tick_df.dropna(how="all")
            
            return del_df, tick_df
        except Exception as e:
            errs.append(f"Public Link Attempt {attempt+1} failed: {str(e)}")
            time.sleep(backoff_factor ** attempt)

    raise RuntimeError(
        "CRITICAL: Failed to load Google Sheet datasets.\n"
        "Please ensure gcp_service_account secrets are configured OR verify the spreadsheet "
        "is shared publicly as 'Anyone with link can view'.\n"
        "Trace details:\n" + "\n".join(errs)
    )