"""
processors/manychat_funil.py
================================================================================
Funil de etapas DENTRO do fluxo do ManyChat, por fluxo (pix_boleto_gerado,
pix_boleto_expirado, carrinho_abandonado, boas_vindas):

    recebeu  →  entrou  →  engajou

Fonte: aba `eventos_manychat` (gravada pelo Cloudflare Worker
recovery-flow-tracker). Schema: ts | telefone | subscriber_id | fluxo | etapa

Sem conversão de venda, sem cruzamento com outras planilhas — tudo de dentro
do ManyChat (complementar à aba "Efetividade ManyChat", que cruza clique com
compra). Pessoas distintas por etapa = chave por subscriber_id (fallback
telefone canônico).
"""

import pandas as pd
from datetime import date
import streamlit as st

from clients.sheets import get_eventos_manychat

ETAPAS = ["recebeu", "entrou", "engajou"]
ETAPA_LABEL = {"recebeu": "Recebeu", "entrou": "Entrou", "engajou": "Engajou"}

LABELS = {
    "pix_boleto_gerado": "PIX/Boleto Gerado",
    "pix_boleto_expirado": "PIX/Boleto Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
    "boas_vindas": "Boas-vindas",
}
ALL_FLUXOS = list(LABELS.keys())


def _canon(phone: str) -> str:
    """Chave canônica de telefone — a variante de 11 dígitos (com 9) quando
    existe, pra o mesmo número casar independente do formato."""
    from utils import phone_variants
    variants = phone_variants(phone)
    eleven = [v for v in variants if len(v) == 11]
    if eleven:
        return eleven[0]
    return max(variants, key=len) if variants else ""


def _person_key(row) -> str:
    """Identidade da pessoa: subscriber_id quando existe, senão telefone canônico."""
    sid = str(row.get("subscriber_id", "")).strip()
    if sid and sid.lower() not in ("", "nan", "none"):
        return f"s:{sid}"
    phone = _canon(str(row.get("telefone", "")))
    return f"p:{phone}" if phone else ""


@st.cache_data(ttl=300, show_spinner=False)
def build_funis(start_date: date, end_date: date) -> dict:
    """Retorna {'resumo': df_por_fluxo}. resumo tem colunas: fluxo, Fluxo,
    Recebeu, Entrou, Engajou, Entrada (%), Engajamento (%), Funil total (%)."""
    df = get_eventos_manychat()
    if df.empty:
        return {"resumo": pd.DataFrame()}

    df = df[df["etapa"].isin(ETAPAS) & (df["fluxo"] != "")]
    mask = (df["ts"].dt.date >= start_date) & (df["ts"].dt.date <= end_date)
    df = df[mask]
    if df.empty:
        return {"resumo": pd.DataFrame()}

    df = df.copy()
    df["pkey"] = df.apply(_person_key, axis=1)
    df = df[df["pkey"] != ""]
    if df.empty:
        return {"resumo": pd.DataFrame()}

    distintos = df.groupby(["fluxo", "etapa"])["pkey"].nunique().reset_index(name="pessoas")
    pivot = distintos.pivot(index="fluxo", columns="etapa", values="pessoas").fillna(0)
    for etapa in ETAPAS:
        if etapa not in pivot.columns:
            pivot[etapa] = 0
    pivot = pivot[ETAPAS].astype(int).reset_index()

    rows = []
    for _, r in pivot.iterrows():
        rec, ent, eng = int(r["recebeu"]), int(r["entrou"]), int(r["engajou"])
        fluxo = r["fluxo"]
        rows.append({
            "fluxo": fluxo,
            "Fluxo": LABELS.get(fluxo, fluxo.replace("_", " ").title()),
            "Recebeu": rec,
            "Entrou": ent,
            "Engajou": eng,
            "Entrada (%)": round(ent / rec * 100, 1) if rec else 0.0,
            "Engajamento (%)": round(eng / ent * 100, 1) if ent else 0.0,
            "Funil total (%)": round(eng / rec * 100, 1) if rec else 0.0,
        })
    resumo = pd.DataFrame(rows).sort_values("Recebeu", ascending=False)
    return {"resumo": resumo}
