import unicodedata
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


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip().lower())


def _strip_tz(series: pd.Series) -> pd.Series:
    """Remove timezone info para permitir comparações entre colunas naive/aware."""
    if series.dt.tz is not None:
        return series.dt.tz_localize(None)
    return series


def _find_phone_col(df: pd.DataFrame) -> str | None:
    """Detecta coluna de telefone independente do nome usado."""
    candidates = ("telefone", "phone", "whatsapp", "celular", "numero", "número", "fone", "tel")
    for col in df.columns:
        if _norm(col) in candidates:
            return col
    # fallback: qualquer coluna cujo nome contenha "phone" ou "tel"
    for col in df.columns:
        cn = _norm(col)
        if "phone" in cn or "tel" in cn or "whats" in cn or "celul" in cn:
            return col
    return None


def _load_tab(spreadsheet_id: str, tab_name: str) -> pd.DataFrame:
    try:
        gc = _client()
        sheet = gc.open_by_key(spreadsheet_id)
        ws = sheet.worksheet(tab_name)
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        phone_col = _find_phone_col(df)
        if phone_col and phone_col != "telefone":
            df = df.rename(columns={phone_col: "telefone"})
        if "telefone" in df.columns:
            df["telefone"] = df["telefone"].astype(str).apply(normalize_phone)
        return df
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()


def _clean_tipo(val) -> str:
    """Limpa rótulo de tipo: remove wrapper de template do Make que não renderizou.
    Ex: '{{ "boleto_expirado"}}' -> 'boleto_expirado'."""
    s = str(val or "").strip()
    if s.startswith("{{") and s.endswith("}}"):
        s = s.strip("{}").strip().strip('"').strip("'").strip()
    return s


@st.cache_data(ttl=300, show_spinner=False)
def get_recuperacoes() -> pd.DataFrame:
    df = _load_tab(config.SPREADSHEET_ID, "recuperacoes")
    if df.empty:
        return df
    if "tipo" in df.columns:
        df["tipo"] = df["tipo"].apply(_clean_tipo)
    df["evento_em"] = pd.to_datetime(df.get("evento_em"), errors="coerce")
    df["evento_em"] = _strip_tz(df["evento_em"])
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
def get_cliques_manychat() -> pd.DataFrame:
    """Cliques nos botões das mensagens do ManyChat (gravados pelo Cloudflare
    Worker). Uma linha por clique. Colunas: clicado_em, telefone,
    subscriber_id, tipo, url."""
    df = _load_tab(config.SPREADSHEET_ID, "cliques_manychat")
    if df.empty:
        return df
    df.columns = [c.strip() for c in df.columns]
    if "tipo" in df.columns:
        df["tipo"] = df["tipo"].apply(_clean_tipo).str.lower()
    df["clicado_em"] = pd.to_datetime(df.get("clicado_em"), errors="coerce", utc=True)
    df["clicado_em"] = _strip_tz(df["clicado_em"])
    if "subscriber_id" in df.columns:
        df["subscriber_id"] = df["subscriber_id"].astype(str)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_eventos_manychat() -> pd.DataFrame:
    """Eventos de etapa dos fluxos do ManyChat (gravados pelo Cloudflare Worker
    recovery-flow-tracker). Uma linha por evento. Colunas: ts, telefone,
    subscriber_id, fluxo, etapa."""
    df = _load_tab(config.SPREADSHEET_ID, "eventos_manychat")
    if df.empty:
        return df
    df.columns = [c.strip() for c in df.columns]
    if "fluxo" in df.columns:
        df["fluxo"] = df["fluxo"].apply(_clean_tipo).str.lower()
    if "etapa" in df.columns:
        df["etapa"] = df["etapa"].apply(_clean_tipo).str.lower()
    df["ts"] = pd.to_datetime(df.get("ts"), errors="coerce", utc=True)
    df["ts"] = _strip_tz(df["ts"])
    if "subscriber_id" in df.columns:
        df["subscriber_id"] = df["subscriber_id"].astype(str)
    return df


def _detect_phone_col_by_values(df: pd.DataFrame) -> str | None:
    """Detecta qual coluna contém telefones varrendo os valores (não o nome da coluna)."""
    import re
    phone_re = re.compile(r"^55\d{10,11}$|^\d{10,11}$")
    best_col, best_count = None, 0
    for col in df.columns:
        sample = df[col].dropna().astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        count = sample.str.match(phone_re).sum()
        if count > best_count:
            best_count = count
            best_col = col
    return best_col if best_count > 0 else None


@st.cache_data(ttl=300, show_spinner=False)
def get_grupo() -> pd.DataFrame:
    """Carrega a planilha de membros do grupo (via Make automation)."""
    sid = config.GRUPO_SPREADSHEET_ID
    if not sid:
        return pd.DataFrame()
    try:
        gc = _client()
        sheet = gc.open_by_key(sid)
        ws = sheet.sheet1
        # Usa get_all_values para ter controle total sobre headers/dados
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame()
        # Linha 0 pode ser header real ou primeira linha de dados com nomes de campo do Make
        # Cria DataFrame com linha 0 como header e restante como dados
        df = pd.DataFrame(rows[1:], columns=rows[0])
        df.columns = [str(c).strip() for c in df.columns]

        # Detecta coluna de telefone pelo conteúdo dos valores
        phone_col = _detect_phone_col_by_values(df)
        if phone_col is None:
            return pd.DataFrame()
        df = df.rename(columns={phone_col: "telefone"})
        df["telefone"] = df["telefone"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).apply(normalize_phone)
        df = df[df["telefone"].str.len() >= 10]

        # Detecta coluna de data de entrada pelo conteúdo (ISO 8601)
        import re
        iso_re = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
        for col in df.columns:
            if col == "telefone":
                continue
            sample = df[col].dropna().astype(str)
            if sample.str.match(iso_re).sum() > len(sample) * 0.5:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True).dt.tz_localize(None)
                df = df.rename(columns={col: "data_entrada_grupo"})
                break

        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def get_compras() -> pd.DataFrame:
    sid = config.COMPRADORES_SPREADSHEET_ID
    tab = config.COMPRADORES_TAB
    if not sid:
        return pd.DataFrame()

    df = _load_tab(sid, tab)
    if df.empty:
        return df

    df.columns = [c.strip() for c in df.columns]

    rename = {}
    for col in df.columns:
        cn = _norm(col)
        if cn in ("preço", "preco", "price"):
            rename[col] = "valor"
        elif "cria" in cn or cn in ("created_at", "data"):
            rename[col] = "compra_em"
        elif "pagamento" in cn or cn == "payment method":
            rename[col] = "payment_method"
    df = df.rename(columns=rename)

    df["compra_em"] = pd.to_datetime(df.get("compra_em"), errors="coerce")
    df["compra_em"] = _strip_tz(df["compra_em"])

    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0).astype(float)
        # Detecção por linha: valores >= 1000 sem casas decimais são centavos (ex: 3700 → 37)
        mask = (df["valor"] >= 1000) & (df["valor"] % 1 == 0)
        df.loc[mask, "valor"] = df.loc[mask, "valor"] / 100

    return df
