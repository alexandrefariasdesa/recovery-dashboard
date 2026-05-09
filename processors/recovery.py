import pandas as pd
from datetime import date
import streamlit as st

from clients.sheets import get_recuperacoes, get_compras

_LABELS = {
    "boleto_gerado": "Boleto Gerado",
    "boleto_expirado": "Boleto Expirado",
    "pix_gerado": "PIX Gerado",
    "pix_expirado": "PIX Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
}

# Eventos que disparam recuperação (ManyChat é acionado nesses)
_RECOVERY_TRIGGERS = {"boleto_expirado", "pix_expirado", "carrinho_abandonado"}


@st.cache_data(ttl=300, show_spinner=False)
def build_recovery_dataframe(start_date: date, end_date: date) -> pd.DataFrame:
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

    # Índice de compras por telefone → compra mais recente
    paid_by_phone: dict[str, pd.Series] = {}
    if not compras.empty:
        for _, row in compras.dropna(subset=["compra_em"]).iterrows():
            phone = row.get("telefone", "")
            if not phone:
                continue
            existing = paid_by_phone.get(phone)
            if existing is None or row["compra_em"] > existing["compra_em"]:
                paid_by_phone[phone] = row

    def _check(row: pd.Series) -> pd.Series:
        if row.get("tipo") not in _RECOVERY_TRIGGERS:
            return pd.Series({"converteu": False, "valor_recuperado": 0.0, "data_pagamento": pd.NaT})

        paid = paid_by_phone.get(row["telefone"])
        if paid is not None and pd.notna(paid["compra_em"]) and paid["compra_em"] > row["evento_em"]:
            return pd.Series({
                "converteu": True,
                "valor_recuperado": float(paid["valor"]),
                "data_pagamento": paid["compra_em"],
            })
        return pd.Series({"converteu": False, "valor_recuperado": 0.0, "data_pagamento": pd.NaT})

    df[["converteu", "valor_recuperado", "data_pagamento"]] = df.apply(_check, axis=1)
    df["recovery_label"] = df["tipo"].map(_LABELS).fillna(df["tipo"])
    df["is_trigger"] = df["tipo"].isin(_RECOVERY_TRIGGERS)

    return df
