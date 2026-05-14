from dotenv import load_dotenv
import os

load_dotenv()


def _get(key: str, default: str = "") -> str:
    """Read from st.secrets (Streamlit Cloud) then fall back to env / default."""
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, default)


# Google Sheets
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SPREADSHEET_ID = _get("SPREADSHEET_ID", "")

# SendFlow
SENDFLOW_TOKEN = _get("SENDFLOW_TOKEN", "")
SENDFLOW_BASE_URL = _get("SENDFLOW_BASE_URL", "https://sendflow.pro/sendapi")
SENDFLOW_ACCOUNT_ID = _get("SENDFLOW_ACCOUNT_ID", "")
SENDFLOW_GROUP_ID = _get("SENDFLOW_GROUP_ID", "")  # groupId alvo para filtrar

# Planilha de compradores
COMPRADORES_SPREADSHEET_ID = _get("COMPRADORES_SPREADSHEET_ID", "")
COMPRADORES_TAB = _get("COMPRADORES_TAB", "Leads")

# Planilha de membros do grupo (via Make automation)
GRUPO_SPREADSHEET_ID = _get("GRUPO_SPREADSHEET_ID", "")

# Produto low ticket
LOW_TICKET_PRODUCT = _get("LOW_TICKET_PRODUCT", "Posições Secretas")
