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
