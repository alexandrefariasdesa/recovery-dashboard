import pandas as pd
from datetime import date
import streamlit as st

import config
from clients.sheets import get_compras, get_grupo
from utils import phone_variants


def build_upsell_dataframe(start_date: date, end_date: date) -> pd.DataFrame:
    compras = get_compras()
    if compras.empty:
        return pd.DataFrame()

    lower = config.LOW_TICKET_PRODUCT.lower()

    if "produto" in compras.columns:
        mask_produto = compras["produto"].str.lower().str.contains(lower[:10], na=False)
    else:
        mask_produto = pd.Series([True] * len(compras), index=compras.index)

    mask = (
        mask_produto
        & (compras["compra_em"].dt.date >= start_date)
        & (compras["compra_em"].dt.date <= end_date)
    )
    df = compras[mask].copy()
    if df.empty:
        return df

    grupo = get_grupo()
    if not grupo.empty and "telefone" in grupo.columns:
        # Constrói set com todas as variantes (com/sem 9 do celular BR)
        grupo_variants: set[str] = set()
        for p in grupo["telefone"].dropna().unique():
            grupo_variants.update(phone_variants(p))

        df["entrou_no_grupo"] = df["telefone"].apply(
            lambda p: bool(phone_variants(p) & grupo_variants)
        )

        if "data_entrada_grupo" in grupo.columns:
            # mapeia cada variante → data mais recente de entrada
            date_map: dict[str, pd.Timestamp] = {}
            for _, row in grupo.dropna(subset=["data_entrada_grupo"]).iterrows():
                for v in phone_variants(row["telefone"]):
                    existing = date_map.get(v)
                    if existing is None or row["data_entrada_grupo"] > existing:
                        date_map[v] = row["data_entrada_grupo"]

            def _get_date(p):
                for v in phone_variants(p):
                    if v in date_map:
                        return date_map[v]
                return pd.NaT

            df["data_entrada_grupo"] = df["telefone"].apply(_get_date)
        else:
            df["data_entrada_grupo"] = pd.NaT
    else:
        df["entrou_no_grupo"] = False
        df["data_entrada_grupo"] = pd.NaT

    return df
