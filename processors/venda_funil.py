"""
processors/venda_funil.py
================================================================================
Funil do fluxo `disparo_venda` (disparo via API pra venda de produto) dentro do
ManyChat, com BIFURCAÇÃO depois do clique:

    recebeu → clicou → ┬ calculando → respondeu → pitch 1 → pitch 2 → pitch 3
                       └ sentindo   → respondeu → pitch 1 → pitch 2 → pitch 3

Fonte: aba `eventos_manychat` (gravada pelo Cloudflare Worker
recovery-flow-tracker). Schema: ts | telefone | subscriber_id | fluxo | etapa
O braço vai codificado no nome da etapa (ex: `calculando_pitch_2`).

Pessoas distintas por etapa = chave por subscriber_id (fallback telefone
canônico), igual ao processors/manychat_funil.py — clicar 2x não dobra.
"""

import pandas as pd
from datetime import date
import streamlit as st

from clients.sheets import get_eventos_manychat

FLUXO = "disparo_venda"

BRACOS = ["calculando", "sentindo"]
BRACO_LABEL = {"calculando": "Calculando", "sentindo": "Sentindo"}

# Etapas de cada braço, na ordem do funil (depois da escolha do braço)
SUB_ETAPAS = ["respondeu", "pitch_1", "pitch_2", "pitch_3"]
SUB_LABEL = {
    "respondeu": "Respondeu",
    "pitch_1": "Pitch 1",
    "pitch_2": "Pitch 2",
    "pitch_3": "Pitch 3",
}


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
def build_venda_funil(start_date: date, end_date: date) -> dict:
    """Retorna:
      - 'geral': {'recebeu': n, 'clicou': n}
      - 'bracos': {braco: {'escolheu': n, 'respondeu': n, 'pitch_1': n, ...}}
      - 'tabela': DataFrame comparativo dos 2 braços (contagens + taxas)
    Contagens = pessoas distintas por etapa no período."""
    vazio = {"geral": {"recebeu": 0, "clicou": 0}, "bracos": {}, "tabela": pd.DataFrame()}

    df = get_eventos_manychat()
    if df.empty or "fluxo" not in df.columns:
        return vazio

    df = df[df["fluxo"] == FLUXO]
    mask = (df["ts"].dt.date >= start_date) & (df["ts"].dt.date <= end_date)
    df = df[mask]
    if df.empty:
        return vazio

    df = df.copy()
    df["pkey"] = df.apply(_person_key, axis=1)
    df = df[df["pkey"] != ""]
    if df.empty:
        return vazio

    pessoas = df.groupby("etapa")["pkey"].nunique().to_dict()

    def n(etapa: str) -> int:
        return int(pessoas.get(etapa, 0))

    geral = {"recebeu": n("recebeu"), "clicou": n("clicou")}

    bracos = {}
    for braco in BRACOS:
        bracos[braco] = {"escolheu": n(braco)}
        for sub in SUB_ETAPAS:
            bracos[braco][sub] = n(f"{braco}_{sub}")

    rows = []
    for braco in BRACOS:
        b = bracos[braco]
        esc = b["escolheu"]
        row = {
            "braco": braco,
            "Opção": BRACO_LABEL[braco],
            "Escolheu": esc,
        }
        anterior = esc
        for sub in SUB_ETAPAS:
            atual = b[sub]
            row[SUB_LABEL[sub]] = atual
            row[f"{SUB_LABEL[sub]} (%)"] = round(atual / anterior * 100, 1) if anterior else 0.0
            anterior = atual
        row["Funil total (%)"] = round(b["pitch_3"] / esc * 100, 1) if esc else 0.0
        rows.append(row)

    tabela = pd.DataFrame(rows)
    return {"geral": geral, "bracos": bracos, "tabela": tabela}
