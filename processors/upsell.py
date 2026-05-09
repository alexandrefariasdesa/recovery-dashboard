import pandas as pd
from datetime import date
import streamlit as st

import config
from clients.sheets import get_compras
from clients.sendflow import get_group_members


@st.cache_data(ttl=300, show_spinner=False)
def build_upsell_dataframe(start_date: date, end_date: date) -> pd.DataFrame:
    compras = get_compras()
    if compras.empty:
        return pd.DataFrame()

    lower = config.LOW_TICKET_PRODUCT.lower()
    mask = (
        compras["produto"].str.lower().str.contains(lower, na=False) &
        (compras["compra_em"].dt.date >= start_date) &
        (compras["compra_em"].dt.date <= end_date)
    )
    df = compras[mask].copy()
    if df.empty:
        return df

    try:
        members = get_group_members()
        member_phones = {m["phone_normalized"] for m in members if m.get("phone_normalized")}
        member_dates = {
            m["phone_normalized"]: m.get("added_at") or m.get("created_at", "")
            for m in members if m.get("phone_normalized")
        }
    except Exception:
        member_phones = set()
        member_dates = {}

    df["entrou_no_grupo"] = df["telefone"].isin(member_phones)
    df["data_entrada_grupo"] = df["telefone"].map(lambda p: member_dates.get(p, ""))

    return df
