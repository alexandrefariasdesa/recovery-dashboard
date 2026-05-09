import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
import config
from utils import normalize_phone

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _client():
    try:
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=_SCOPES,
            )
            return gspread.authorize(creds)
    except Exception:
        pass
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=_SCOPES,
    )
    return gspread.authorize(creds)


def _load_tab(tab_name: str) -> pd.DataFrame:
    try:
        gc = _client()
        sheet = gc.open_by_key(config.SPREADSHEET_ID)
        ws = sheet.worksheet(tab_name)
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        if "telefone" in df.columns:
            df["telefone"] = df["telefone"].astype(str).apply(normalize_phone)
        return df
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def get_recuperacoes() -> pd.DataFrame:
    df = _load_tab("recuperacoes")
    if df.empty:
        return df
    df["evento_em"] = pd.to_datetime(df.get("evento_em"), errors="coerce")
    df["valor"] = pd.to_numeric(df.get("valor", 0), errors="coerce").fillna(0)
    if "converteu" not in df.columns:
        df["converteu"] = False
    else:
        df["converteu"] = df["converteu"].astype(str).str.lower().isin(["true", "1", "sim", "yes"])
    if "valor_recuperado" not in df.columns:
        df["valor_recuperado"] = 0.0
    else:
        df["valor_recuperado"] = pd.to_numeric(df["valor_recuperado"], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_compras() -> pd.DataFrame:
    df = _load_tab("compras")
    if df.empty:
        return df
    df["compra_em"] = pd.to_datetime(df.get("compra_em"), errors="coerce")
    df["valor"] = pd.to_numeric(df.get("valor", 0), errors="coerce").fillna(0)
    if "entrou_no_grupo" not in df.columns:
        df["entrou_no_grupo"] = False
    else:
        df["entrou_no_grupo"] = df["entrou_no_grupo"].astype(str).str.lower().isin(["true", "1", "sim", "yes"])
    return df
