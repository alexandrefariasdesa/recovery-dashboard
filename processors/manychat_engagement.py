"""
processors/manychat_engagement.py
================================================================================
Efetividade das mensagens do ManyChat por tipo de ação:

    recebeu  →  clicou  →  (clicou e) converteu

- Recebeu (denominador): pessoas distintas que dispararam a ação no período.
    · tipos de recuperação (pix/boleto/carrinho)  → aba `recuperacoes`
    · compra_aprovada                              → aba `compras` (quem comprou)
- Clicou (numerador): pessoas distintas com clique registrado (aba
    `cliques_manychat`, gravada pelo Cloudflare Worker no clique do botão).
- Converteu pós-clique: de quem clicou, quantos efetivamente compraram depois
    (cruza com `compras` por telefone, no espírito do processors/recovery.py).

Tudo casado por telefone canônico (resolve o 9 do celular BR via phone_variants).
"""

import pandas as pd
from datetime import date
import streamlit as st

from clients.sheets import get_recuperacoes, get_compras, get_cliques_manychat
from utils import phone_variants

# Tipos rastreados + ordem de exibição. compra_aprovada vem de `compras`,
# o resto vem de `recuperacoes`.
RECOVERY_TIPOS = [
    "pix_gerado", "pix_expirado",
    "carrinho_abandonado",
    "boleto_gerado", "boleto_expirado",
]
ALL_TIPOS = RECOVERY_TIPOS + ["compra_aprovada"]

LABELS = {
    "pix_gerado": "PIX Gerado",
    "pix_expirado": "PIX Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
    "boleto_gerado": "Boleto Gerado",
    "boleto_expirado": "Boleto Expirado",
    "compra_aprovada": "Compra Aprovada",
}


def _canon(phone: str) -> str:
    """Chave canônica de telefone — a variante de 11 dígitos (com 9) quando
    existe, pra o mesmo número casar entre as abas independente do formato."""
    variants = phone_variants(phone)
    eleven = [v for v in variants if len(v) == 11]
    if eleven:
        return eleven[0]
    return max(variants, key=len) if variants else ""


def _compras_index(compras: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """telefone canônico → data da compra mais recente (para checar conversão)."""
    idx: dict[str, pd.Timestamp] = {}
    if compras.empty:
        return idx
    for _, row in compras.dropna(subset=["compra_em"]).iterrows():
        phone = str(row.get("telefone", ""))
        if not phone:
            continue
        key = _canon(phone)
        prev = idx.get(key)
        if prev is None or row["compra_em"] > prev:
            idx[key] = row["compra_em"]
    return idx


@st.cache_data(ttl=300, show_spinner=False)
def build_manychat_engagement(start_date: date, end_date: date) -> dict:
    """Retorna {'resumo': df_por_tipo, 'diario': df_dia_tipo}."""
    recuperacoes = get_recuperacoes()
    compras = get_compras()
    cliques = get_cliques_manychat()

    paid_idx = _compras_index(compras)

    # ── Recebeu (pessoas distintas) e disparos por tipo ──────────────────────
    recebeu: dict[str, set[str]] = {t: set() for t in ALL_TIPOS}
    disparos: dict[str, int] = {t: 0 for t in ALL_TIPOS}
    recebeu_dia: list[dict] = []

    if not recuperacoes.empty:
        mask = (
            (recuperacoes["evento_em"].dt.date >= start_date)
            & (recuperacoes["evento_em"].dt.date <= end_date)
        )
        rec = recuperacoes[mask]
        for _, row in rec.iterrows():
            tipo = str(row.get("tipo", ""))
            if tipo not in RECOVERY_TIPOS:
                continue
            key = _canon(str(row.get("telefone", "")))
            if key:
                recebeu[tipo].add(key)
            disparos[tipo] += 1
            recebeu_dia.append({"dia": row["evento_em"].date(), "tipo": tipo, "_k": key})

    if not compras.empty:
        mask = (
            (compras["compra_em"].dt.date >= start_date)
            & (compras["compra_em"].dt.date <= end_date)
        )
        comp = compras[mask]
        for _, row in comp.iterrows():
            key = _canon(str(row.get("telefone", "")))
            if key:
                recebeu["compra_aprovada"].add(key)
            disparos["compra_aprovada"] += 1
            recebeu_dia.append({"dia": row["compra_em"].date(), "tipo": "compra_aprovada", "_k": key})

    # ── Clicou (pessoas distintas) por tipo + conversão pós-clique ───────────
    clicou: dict[str, set[str]] = {t: set() for t in ALL_TIPOS}
    converteu_pos: dict[str, set[str]] = {t: set() for t in ALL_TIPOS}
    cliques_dia: list[dict] = []

    if not cliques.empty:
        mask = (
            (cliques["clicado_em"].dt.date >= start_date)
            & (cliques["clicado_em"].dt.date <= end_date)
        )
        clk = cliques[mask]
        for _, row in clk.iterrows():
            tipo = str(row.get("tipo", ""))
            if tipo not in ALL_TIPOS:
                continue
            key = _canon(str(row.get("telefone", "")))
            if key:
                clicou[tipo].add(key)
                # converteu se há compra no/após o dia do clique
                paid = paid_idx.get(key)
                if paid is not None and paid.date() >= row["clicado_em"].date():
                    converteu_pos[tipo].add(key)
            cliques_dia.append({"dia": row["clicado_em"].date(), "tipo": tipo, "_k": key})

    # ── Resumo por tipo ──────────────────────────────────────────────────────
    rows = []
    for tipo in ALL_TIPOS:
        n_rec = len(recebeu[tipo])
        n_clk = len(clicou[tipo])
        n_conv = len(converteu_pos[tipo])
        if n_rec == 0 and n_clk == 0:
            continue
        rows.append({
            "tipo": tipo,
            "Tipo": LABELS[tipo],
            "Recebeu (pessoas)": n_rec,
            "Disparos": disparos[tipo],
            "Clicou (pessoas)": n_clk,
            "CTR (%)": round(n_clk / n_rec * 100, 1) if n_rec else 0.0,
            "Converteu pós-clique": n_conv,
            "Conv. do clique (%)": round(n_conv / n_clk * 100, 1) if n_clk else 0.0,
        })
    resumo = pd.DataFrame(rows)

    # ── Diário (volume recebido vs clicado por tipo) ─────────────────────────
    rec_df = pd.DataFrame(recebeu_dia)
    clk_df = pd.DataFrame(cliques_dia)

    rec_daily = (
        rec_df.groupby(["dia", "tipo"])["_k"].nunique().reset_index(name="recebidos")
        if not rec_df.empty else pd.DataFrame(columns=["dia", "tipo", "recebidos"])
    )
    clk_daily = (
        clk_df.groupby(["dia", "tipo"])["_k"].nunique().reset_index(name="cliques")
        if not clk_df.empty else pd.DataFrame(columns=["dia", "tipo", "cliques"])
    )
    diario = pd.merge(rec_daily, clk_daily, on=["dia", "tipo"], how="outer")
    if not diario.empty:
        diario[["recebidos", "cliques"]] = diario[["recebidos", "cliques"]].fillna(0).astype(int)
        diario["ctr"] = (diario["cliques"] / diario["recebidos"].replace(0, pd.NA) * 100).round(1)
        diario = diario.sort_values("dia")

    return {"resumo": resumo, "diario": diario}
