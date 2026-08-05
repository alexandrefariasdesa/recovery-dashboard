from dotenv import load_dotenv
import os

load_dotenv()
# Credenciais do Postgres (migração) ficam separadas, em .env.supabase.
load_dotenv(".env.supabase", override=False)


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

# ── Migração p/ Postgres (Supabase) ──────────────────────────────────────────
# Flag reversível: com USE_POSTGRES=1 a aba de recuperação lê do banco (view
# v_recovery_conversao); senão, do Google Sheets (comportamento atual).
USE_POSTGRES = _get("USE_POSTGRES", "").strip().lower() in ("1", "true", "yes", "on")
PG_HOST = _get("PG_HOST", "aws-0-sa-east-1.pooler.supabase.com")
PG_PORT = int(_get("PG_PORT", "6543") or "6543")
PG_USER = _get("PG_USER", "")
PG_PASSWORD = _get("PG_PASSWORD", "") or _get("SUPABASE_DB_PASSWORD", "")
PG_DBNAME = _get("PG_DBNAME", "postgres")
