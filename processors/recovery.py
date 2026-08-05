import pandas as pd
from datetime import date
import streamlit as st

from clients.sheets import get_recuperacoes, get_compras
from utils import phone_variants

_LABELS = {
    "boleto_gerado": "Boleto Gerado",
    "boleto_expirado": "Boleto Expirado",
    "pix_gerado": "PIX Gerado",
    "pix_expirado": "PIX Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
}


@st.cache_data(ttl=300, show_spinner=False)
def build_recovery_dataframe(start_date: date, end_date: date) -> pd.DataFrame:
    # Migração: com o flag ligado, lê a conversão pronta do Postgres (view
    # v_recovery_conversao) em vez de cruzar as planilhas em Python. Mesmas
    # colunas de saída — a aba não muda. Reversível: desliga o flag e volta.
    import config
    if getattr(config, "USE_POSTGRES", False):
        from clients.postgres import fetch_recovery_conversao
        return fetch_recovery_conversao(start_date, end_date)

    recuperacoes = get_recuperacoes()
    compras = get_compras()

    if recuperacoes.empty:
        return pd.DataFrame()

    mask = (
        (recuperacoes["evento_em"].dt.date >= start_date) &
        (recuperacoes["evento_em"].dt.date <= end_date)
    )
    df = recuperacoes[mask].copy()
    if df.empty:
        return df

    # Índice de compras por telefone (todas as variantes com/sem 9)
    paid_by_phone: dict[str, pd.Series] = {}
    if not compras.empty:
        for _, row in compras.dropna(subset=["compra_em"]).iterrows():
            phone = str(row.get("telefone", ""))
            if not phone:
                continue
            for v in phone_variants(phone):
                existing = paid_by_phone.get(v)
                if existing is None or row["compra_em"] > existing["compra_em"]:
                    paid_by_phone[v] = row

    def _check(row: pd.Series) -> pd.Series:
        phone = str(row.get("telefone", ""))
        paid = None
        for v in phone_variants(phone):
            paid = paid_by_phone.get(v)
            if paid is not None:
                break
        if paid is not None and pd.notna(paid["compra_em"]):
            # Compara apenas a data (dia) — evento_em pode refletir horário de export em massa
            if paid["compra_em"].date() >= row["evento_em"].date():
                return pd.Series({
                    "converteu": True,
                    "valor_recuperado": float(paid["valor"]),
                    "data_pagamento": paid["compra_em"],
                    "produto_comprado": str(paid.get("produto", "")),
                })
        return pd.Series({
            "converteu": False,
            "valor_recuperado": 0.0,
            "data_pagamento": pd.NaT,
            "produto_comprado": "",
        })

    df[["converteu", "valor_recuperado", "data_pagamento", "produto_comprado"]] = df.apply(_check, axis=1)
    df["recovery_label"] = df["tipo"].map(_LABELS).fillna(df["tipo"])

    return df
