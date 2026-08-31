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
    st.caption(
        "O fluxo é do Instagram e não pede contato, então não dá para casar a "
        "pessoa com a compra. A chave é a **origem**: a Payt manda o UTM do link "
        "no webhook e ele fica em `compras.utm`. Uma venda com o UTM deste fluxo "
        "é uma venda deste fluxo, sem precisar saber quem é."
    )

    utms = data.get("utms")
    com_utm = data.get("compras_com_utm", 0)
    no_periodo = data.get("compras_periodo", 0)

    if utms is None or utms.empty:
        st.info(
            f"**Nenhuma das {_br(no_periodo)} compras do período tem UTM "
            "gravado ainda.** A captura começa a valer no deploy do webhook "
            "`payt-webhook` (migration 0020 já aplicada) — daí em diante toda "
            "compra aprovada chega com a origem, e este bloco passa a responder "
            "sozinho. Vendas anteriores só entram por backfill a partir da Payt."
        )
    else:
        rotulos = [
            f"{r.utm_source} · {r.utm_campaign} · {r.utm_content}"
            for r in utms.itertuples()
        ]
        utms = utms.assign(Origem=rotulos)
        # Palpite inicial: o que parece boas-vindas/ManyChat já vem marcado, mas
        # quem decide é você — o slug do link é escolhido no ManyChat, não aqui.
        padrao = [
            rot for rot in rotulos
            if any(t in rot.lower() for t in ("boas", "bv", "welcome", "manychat", "seguidor"))
        ]
        escolhidas = st.multiselect(
            "Quais origens são deste fluxo?", rotulos, default=padrao,
            key="bv_ig_utms",
        )
        sel = utms[utms["Origem"].isin(escolhidas)]
        compras_fluxo = int(sel["compras"].sum()) if not sel.empty else 0
        receita_fluxo = float(sel["receita"].sum()) if not sel.empty else 0.0
        valor = "R$ " + (f"{receita_fluxo:,.2f}"
                         .replace(",", "X").replace(".", ",").replace("X", "."))

        c1, c2, c3 = st.columns(3)
        c1.metric("Compras deste fluxo", _br(compras_fluxo))
        c2.metric("Receita do fluxo", valor)
        c3.metric("Compras por pessoa que engajou",
                  f"{(compras_fluxo / engajou * 100):.2f}%" if engajou else "—")

        st.dataframe(
            utms[["Origem", "compras", "receita"]]
            .rename(columns={"compras": "Compras", "receita": "Receita"}),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            f"{_br(com_utm)} de {_br(no_periodo)} compras do período têm UTM "
            "gravado. As demais são anteriores à captura — não são vendas sem "
            "origem, são vendas de antes da medição."
        )

    # Segunda via: a ponte por telefone, que acende se o fluxo passar a pedir
    # contato. Fica recolhida porque hoje é quase sempre zero.
    identificaveis = data["identificaveis"]
    compraram = data["compraram"]
    with st.expander("Segunda via: atribuição por telefone"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Pessoas no fluxo", _br(recebeu))
        c2.metric("Com telefone", _br(identificaveis), _pct(identificaveis, recebeu))
        c3.metric("Compraram", _br(compraram))
        st.caption(
            "Só existe para quem deixou telefone em algum evento do fluxo. Como "
            "a automação do Instagram não pede contato, esse teto é quase zero "
            "hoje — e ficaria zero também se ninguém tivesse comprado, que é "
            "por que este não é o número que responde a pergunta."
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
