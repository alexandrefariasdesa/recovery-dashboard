"""
components/boas_vindas_ig_tab.py
================================================================================
A tela do fluxo de boas-vindas do Instagram: o funil de três etapas que o
próprio fluxo grava, o ritmo diário e o estado da atribuição de compra.

Mesma gramática das outras páginas de funil — faixa de números no topo, funil,
ritmo, e o aviso honesto no lugar onde falta dado, em vez de um zero mudo.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components.theme import ARDOSIA, PIX, AMBAR
from processors.boas_vindas_ig import ETAPAS, ETAPA_LABEL

ETAPA_COR = {"recebeu": ARDOSIA, "entrou": AMBAR, "engajou": PIX}


def _br(v):
    return f"{int(v):,}".replace(",", ".")


def _pct(parte, todo):
    return f"{(parte / todo * 100):.1f}%" if todo else "—"


def _layout(fig, altura=280):
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=altura,
                      legend_title_text="")
    return fig


def render_boas_vindas_ig(data: dict) -> None:
    recebeu = data["recebeu"]
    entrou = data["entrou"]
    engajou = data["engajou"]

    st.caption(
        "Automação **boas vindas posições 2** (Instagram, no ar desde "
        "17/07/2026). Cada etapa é um tijolo de External Request dentro do "
        "próprio fluxo, gravado pelo Worker `recovery-flow-tracker`. Pessoas "
        "distintas por etapa — quem clica duas vezes não conta duas."
    )

    if not recebeu:
        st.info(
            "Nenhum evento do fluxo de boas-vindas do Instagram no período. "
            "Se isso for inesperado, confira em Pulso se o Worker "
            "`recovery-flow-tracker` continua recebendo."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Receberam", _br(recebeu))
    c2.metric("Entraram", _br(entrou), _pct(entrou, recebeu))
    c3.metric("Engajaram", _br(engajou), _pct(engajou, entrou))
    st.caption(
        "Delta = taxa sobre a etapa **anterior** (Entrou ÷ Recebeu · Engajou ÷ "
        f"Entrou). Do topo ao fim: **{_pct(engajou, recebeu)}** de quem recebeu "
        "chegou a engajar."
    )

    st.divider()

    esq, dir_ = st.columns(2)

    with esq:
        st.subheader("O funil")
        fig = go.Figure(go.Bar(
            x=[data["funil"].loc[data["funil"]["etapa"] == e, "Pessoas"].iloc[0]
               for e in ETAPAS],
            y=[ETAPA_LABEL[e] for e in ETAPAS],
            orientation="h",
            marker={"color": [ETAPA_COR[e] for e in ETAPAS]},
            text=[_br(data["funil"].loc[data["funil"]["etapa"] == e, "Pessoas"].iloc[0])
                  for e in ETAPAS],
            textposition="auto",
        ))
        fig.update_layout(yaxis={"autorange": "reversed"}, xaxis_title="Pessoas")
        st.plotly_chart(_layout(fig), use_container_width=True)

    with dir_:
        st.subheader("Ritmo diário")
        diario = data["diario"]
        if diario is None or diario.empty:
            st.info("Sem série diária no período.")
        else:
            fig = px.line(
                diario, x="dia", y="pessoas", color="Etapa", markers=True,
                color_discrete_map={ETAPA_LABEL[e]: ETAPA_COR[e] for e in ETAPAS},
            )
            fig.update_layout(xaxis_title="", yaxis_title="Pessoas")
            st.plotly_chart(_layout(fig), use_container_width=True)

    st.divider()

    # ── Compra ──────────────────────────────────────────────────────────────
    st.subheader("Quantas compraram")
    identificaveis = data["identificaveis"]
    compraram = data["compraram"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Pessoas no fluxo", _br(recebeu))
    c2.metric("Com telefone (atribuível)", _br(identificaveis),
              _pct(identificaveis, recebeu))
    c3.metric("Compraram (atribuídas)", _br(compraram))

    if identificaveis < max(1, recebeu * 0.01):
        st.warning(
            "**Esta pergunta ainda não tem resposta — e o motivo não é falta de "
            "venda.** O fluxo é do Instagram e não pede contato: os eventos "
            "chegam só com `subscriber_id`, enquanto `compras` identifica a "
            f"pessoa por telefone/e-mail. No período, {_br(identificaveis)} de "
            f"{_br(recebeu)} pessoas deixaram telefone em algum evento, então o "
            "teto do que dá para atribuir é esse — não o número de compras.\n\n"
            "Para o número existir, o fluxo precisa carregar identidade até a "
            "compra. Dois caminhos, do mais barato ao mais completo:\n\n"
            "1. **Levar o `subscriber_id` até o checkout** — o botão de oferta "
            "sai com o id na URL (`?src=ig_bv_{{subscriber_id}}`) e o webhook de "
            "compra guarda esse campo. Liga a venda sem pedir nada à pessoa.\n"
            "2. **Pedir WhatsApp dentro do fluxo** — uma etapa a mais, mas passa "
            "a casar com tudo que já existe no painel (recuperação, grupo, aula)."
        )
    else:
        receita = "R$ " + (f"{float(data['receita']):,.2f}"
                           .replace(",", "X").replace(".", ",").replace("X", "."))
        st.caption(
            f"Atribuição pela ponte de telefone: {_br(compraram)} de "
            f"{_br(identificaveis)} pessoas identificáveis compraram "
            f"({_pct(compraram, identificaveis)}) — {receita} em vendas."
        )

    # ── Outros fluxos de boas-vindas ────────────────────────────────────────
    outros = data.get("outros")
    if outros is not None and not outros.empty:
        st.divider()
        st.subheader("Outros fluxos de boas-vindas no período")
        st.caption(
            "Fluxos de WhatsApp com slug próprio. Estão aqui como contexto — "
            "não entram no funil do Instagram acima."
        )
        tabela = (outros.pivot_table(index="Fluxo", columns="etapa",
                                     values="pessoas", aggfunc="sum", fill_value=0)
                  .reset_index())
        st.dataframe(tabela, use_container_width=True, hide_index=True)
