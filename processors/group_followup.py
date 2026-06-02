import pandas as pd
from datetime import date, timedelta
import streamlit as st

from clients.sheets import get_compras, get_grupo
from utils import phone_variants


@st.cache_data(ttl=300, show_spinner=False)
def build_group_followup_dataframe(
    reference_date: date,
    cutoff_date: date,
    min_age_days: int = 1,
) -> pd.DataFrame:
    """
    Segmento da 2ª chamada para o grupo: TODOS que compraram (sem filtro de produto),
    comprou há mais de `min_age_days` dia(s), em/depois de `cutoff_date`,
    e ainda NÃO entrou no grupo.

    Espelha o cálculo do Apps Script (apps_script/group_second_call.gs).
    """
    compras = get_compras()
    if compras.empty:
        return pd.DataFrame()

    df = compras.copy()
    df = df.dropna(subset=["compra_em"])

    grupo = get_grupo()
    grupo_variants: set[str] = set()
    if not grupo.empty and "telefone" in grupo.columns:
        for p in grupo["telefone"].dropna().unique():
            grupo_variants.update(phone_variants(p))

    df["entrou_no_grupo"] = df["telefone"].apply(
        lambda p: bool(phone_variants(p) & grupo_variants)
    )

    limite = reference_date - timedelta(days=min_age_days)  # comprou em/antes disso
    df["dias_desde_compra"] = (
        pd.Timestamp(reference_date) - df["compra_em"].dt.normalize()
    ).dt.days

    df["pendente_2a_chamada"] = (
        (~df["entrou_no_grupo"])
        & (df["compra_em"].dt.date <= limite)
        & (df["compra_em"].dt.date >= cutoff_date)
    )

    return df
