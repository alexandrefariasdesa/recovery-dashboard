"""
Leitura da conversão de recuperação direto do Postgres (view v_recovery_conversao).

Alternativa ao caminho Sheets (processors/recovery.py). Ligado pelo flag
config.USE_POSTGRES. Devolve um DataFrame com AS MESMAS colunas que
build_recovery_dataframe produz, pra aba de recuperação não precisar mudar.
"""
import pandas as pd
import psycopg2

import config

# Mesmos rótulos do processors/recovery.py (duplicado p/ evitar import circular).
_LABELS = {
    "boleto_gerado": "Boleto Gerado",
    "boleto_expirado": "Boleto Expirado",
    "pix_gerado": "PIX Gerado",
    "pix_expirado": "PIX Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
}


def _connect():
    return psycopg2.connect(
        host=config.PG_HOST,
        port=config.PG_PORT,
        user=config.PG_USER,
        password=config.PG_PASSWORD,
        dbname=config.PG_DBNAME,
        connect_timeout=15,
    )


def fetch_recovery_conversao(start_date, end_date) -> pd.DataFrame:
    """Eventos de recuperação + conversão no período (fuso São Paulo), do banco."""
    q = """
        select evento_em, tipo, nome, telefone, valor,
               converteu, valor_recuperado, data_pagamento, produto_comprado
        from v_recovery_conversao
        where (evento_em at time zone 'America/Sao_Paulo')::date between %s and %s
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(q, (start_date, end_date))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df

    # evento_em/data_pagamento vêm timestamptz (UTC) — traz pra parede de relógio
    # de São Paulo e tira o fuso, igual ao caminho Sheets (datas naïve).
    for c in ("evento_em", "data_pagamento"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce").dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)

    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0).astype(float)
    df["valor_recuperado"] = pd.to_numeric(df["valor_recuperado"], errors="coerce").fillna(0.0).astype(float)
    df["converteu"] = df["converteu"].astype(bool)
    df["nome"] = df["nome"].fillna("")
    df["telefone"] = df["telefone"].fillna("")
    df["produto_comprado"] = df["produto_comprado"].fillna("")
    df["recovery_label"] = df["tipo"].map(_LABELS).fillna(df["tipo"])
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Leitores RAW por tabela — espelham as get_* de clients/sheets.py (mesma forma e
# mesmo tratamento de fuso), pra as OUTRAS abas migrarem sem mexer nos processors.
# ─────────────────────────────────────────────────────────────────────────────
def _read(query: str) -> pd.DataFrame:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(query)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=cols)


def _sp_naive(s):
    """timestamptz UTC → naïve na parede de São Paulo (igual get_recuperacoes/compras)."""
    return pd.to_datetime(s, utc=True, errors="coerce").dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)


def _utc_naive(s):
    """timestamptz → naïve em UTC (igual get_eventos/cliques_manychat, que usam utc=True)."""
    return pd.to_datetime(s, utc=True, errors="coerce").dt.tz_localize(None)


def get_recuperacoes_pg() -> pd.DataFrame:
    df = _read("select tipo, evento_em, nome, telefone, valor from recovery_events")
    if df.empty:
        return df
    df["evento_em"] = _sp_naive(df["evento_em"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    df["telefone"] = df["telefone"].fillna("").astype(str)
    df["converteu"] = False
    df["valor_recuperado"] = 0.0
    return df


def get_compras_pg() -> pd.DataFrame:
    df = _read("select nome, telefone, produto, valor, compra_em from compras")
    if df.empty:
        return df
    df["compra_em"] = _sp_naive(df["compra_em"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0).astype(float)
    df["telefone"] = df["telefone"].fillna("").astype(str)
    return df


def get_eventos_manychat_pg() -> pd.DataFrame:
    df = _read("select evento_em as ts, telefone, subscriber_id, fluxo, etapa from manychat_eventos")
    if df.empty:
        return df
    df["ts"] = _utc_naive(df["ts"])
    df["telefone"] = df["telefone"].fillna("").astype(str)
    df["subscriber_id"] = df["subscriber_id"].fillna("").astype(str)
    return df


def get_cliques_manychat_pg() -> pd.DataFrame:
    df = _read("select clicado_em, telefone, subscriber_id, tipo, url from manychat_cliques")
    if df.empty:
        return df
    df["clicado_em"] = _utc_naive(df["clicado_em"])
    df["telefone"] = df["telefone"].fillna("").astype(str)
    df["subscriber_id"] = df["subscriber_id"].fillna("").astype(str)
    return df
