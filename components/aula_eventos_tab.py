"""
components/aula_eventos_tab.py
================================================================================
A página do webinário. Duas peculiaridades em relação às outras:

1. Ela NÃO sabe quais eventos existem. Todos os webhooks da plataforma foram
   cadastrados na mesma URL, então o catálogo é descoberto no banco e a página
   se monta em cima do que chegou. Enquanto nada chegou, ela vira instrução de
   cadastro em vez de tabela vazia — que é o estado em que ela nasce.

2. O primeiro número não é volume, é **quanto do evento dá pra usar**. Um
   webhook que chega sem telefone e sem e-mail não cruza com pessoa nenhuma:
   serve de contador e não serve pra decidir mensagem. A página diz isso na cara
   em vez de deixar o volume parecer resultado.
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from components.theme import dinheiro, grafico

URL_BASE = "https://ztoghqjnctoreozoyvhh.supabase.co/functions/v1/webinar-webhook"


def _br(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _instrucoes() -> None:
    """Estado inicial: ninguém cadastrou nada ainda, ou nada chegou."""
    st.info(
        "**Nenhum evento do webinário chegou ainda.** Esta página se monta "
        "sozinha com o que a plataforma mandar — não tem lista de eventos "
        "fixada no código."
    )
    st.markdown(
        "#### Como cadastrar\n"
        "No painel da Applive, aponte **todos** os webhooks para a mesma URL, "
        "mudando só o `&evento=`:"
    )
    st.code(
        f"{URL_BASE}?token=SEU_TOKEN&evento=entrou_sala\n"
        f"{URL_BASE}?token=SEU_TOKEN&evento=saiu_sala\n"
        f"{URL_BASE}?token=SEU_TOKEN&evento=clicou_oferta\n"
        f"{URL_BASE}?token=SEU_TOKEN&evento=inscricao\n"
        "...  (um por webhook disponível, com o nome que fizer sentido)",
        language="text",
    )
    st.caption(
        "O `&evento=` é o nome que aparece nesta página. Se você esquecer dele, "
        "o receptor tenta adivinhar pelo payload e, no pior caso, grava como "
        "`nao_identificado` — a linha nunca é descartada. O `token` é o secret "
        "`WEBINAR_TOKEN` da edge function."
    )


def _catalogo(cat: pd.DataFrame) -> None:
    st.subheader("O que a plataforma está mandando")
    st.caption(
        "Descoberto no banco, não declarado no código: cada linha é um webhook "
        "que efetivamente chegou pelo menos uma vez."
    )

    total = int(cat["total"].sum())
    sem_chave = int(cat["sem_chave"].sum())
    aproveitavel = total - sem_chave

    c1, c2, c3 = st.columns(3)
    c1.metric("Eventos recebidos", _br(total))
    c2.metric("Tipos diferentes", _br(len(cat)))
    c3.metric(
        "Cruzam com uma pessoa",
        _br(aproveitavel),
        f"{(100.0 * aproveitavel / total if total else 0):.1f}%",
    )

    if sem_chave:
        piores = cat[cat["sem_chave"] > 0].sort_values("sem_chave", ascending=False)
        nomes = ", ".join(f"`{r.evento}` ({_br(r.sem_chave)})" for r in piores.head(4).itertuples())
        st.warning(
            f"**{_br(sem_chave)} eventos chegaram sem telefone e sem e-mail** — "
            f"{nomes}. Eles contam volume mas não encaixam em ninguém: não dá "
            "pra suprimir mensagem nem cruzar com compra. Vale conferir no "
            "painel da Applive se esses webhooks têm como incluir o campo de "
            "contato no payload."
        )

    vis = cat.rename(columns={
        "evento": "Evento", "total": "Total", "d7": "7 dias", "pessoas": "Pessoas",
        "com_telefone": "C/ telefone", "com_email": "C/ e-mail",
        "sem_chave": "Sem chave", "identificavel_pct": "Identificável %",
        "primeiro": "Primeiro", "ultimo": "Último",
    })
    st.dataframe(
        vis[["Evento", "Total", "7 dias", "Pessoas", "C/ telefone", "C/ e-mail",
             "Sem chave", "Identificável %", "Último"]],
        use_container_width=True, hide_index=True,
    )


def _volume(por_dia: pd.DataFrame) -> None:
    if por_dia.empty:
        return
    st.subheader("Volume por dia")
    fig = px.bar(por_dia, x="dia", y="n", color="evento", barmode="stack",
                 labels={"dia": "", "n": "eventos", "evento": ""})
    grafico(fig)


def _dinheiro(compra: pd.DataFrame) -> None:
    if compra.empty:
        return
    st.subheader("Quem fez isso e comprou depois")
    st.caption(
        "A compra conta só se veio **depois** do evento — mesmo desenho da "
        "supressão da recuperação. Compra anterior não é mérito da sala."
    )
    vis = compra.copy()
    vis["valor"] = vis["valor"].map(lambda v: dinheiro(float(v or 0)))
    vis = vis.rename(columns={
        "evento": "Evento", "pessoas": "Pessoas", "compraram": "Compraram",
        "taxa_pct": "Taxa %", "valor": "Valor",
    })
    st.dataframe(vis, use_container_width=True, hide_index=True)


def _pessoas(pessoas: pd.DataFrame) -> None:
    if pessoas.empty:
        return
    st.subheader("Por pessoa")
    st.caption(
        "Uma linha por pessoa; as colunas de evento são quantas vezes ela "
        "disparou cada um. `veio_do_convite` separa quem chegou pelo nosso "
        "WhatsApp de quem veio por fora."
    )
    st.dataframe(pessoas.sort_values("ultimo", ascending=False),
                 use_container_width=True, hide_index=True)


def render_aula_eventos_tab(data: dict) -> None:
    if data.get("vazio"):
        _instrucoes()
        return

    cat: pd.DataFrame = data["catalogo"]
    _catalogo(cat)

    eventos: pd.DataFrame = data.get("eventos", pd.DataFrame())
    if eventos.empty:
        st.divider()
        st.info(
            "Já existem eventos na base, mas nenhum no período selecionado. "
            "Ajuste o período na barra lateral."
        )
        return

    st.divider()
    _volume(data.get("por_dia", pd.DataFrame()))
    st.divider()
    _dinheiro(data.get("compra", pd.DataFrame()))
    st.divider()
    _pessoas(data.get("pessoas", pd.DataFrame()))

    st.divider()
    with st.expander(f"Eventos crus do período ({_br(len(eventos))})"):
        st.dataframe(eventos, use_container_width=True, hide_index=True)
