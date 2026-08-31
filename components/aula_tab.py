import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from components.theme import PIX, grafico


def _br(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def render_aula_tab(data: dict) -> None:
    resumo: dict = data.get("resumo", {})
    funil: pd.DataFrame = data.get("funil", pd.DataFrame())
    por_dia: pd.DataFrame = data.get("por_dia", pd.DataFrame())
    convites: pd.DataFrame = data.get("convites", pd.DataFrame())
    etapas: pd.DataFrame = data.get("etapas", pd.DataFrame())

    st.caption(
        "Convite pra **aula das 19h30** aos 7 dias de compra do Posições Secretas. "
        "A cadência do dia **não** roda dentro do ManyChat: cada mensagem é "
        "disparada pelo `pg_cron` na hora cravada (09h00 · 18h30 · 19h15 · 19h30 BRT) "
        "chamando a edge function `aula-convite`, que fala direto com a API do "
        "ManyChat. Por isso o horário independe de quando a pessoa entrou ou clicou."
    )

    faltando = resumo.get("etapas_sem_fluxo") or []
    if faltando:
        st.warning(
            "Etapas sem fluxo do ManyChat configurado (não disparam): "
            + ", ".join(f"`{e}`" for e in faltando)
            + " — grave o `ns` em `convites_aula_etapas.flow_ns`."
        )

    # ── Números de topo ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Convidadas no período", _br(resumo.get("convidadas", 0)))
    c2.metric("Convite entregue (09h)", _br(resumo.get("convites_ok", 0)))
    c3.metric("Última mensagem (19h30)", _br(resumo.get("ultima_etapa", 0)))
    c4.metric(
        "Retenção da grade",
        f"{resumo.get('retencao', 0.0):.1f}%",
        help="Quantas das que receberam a 1ª mensagem chegaram na última.",
    )

    sem_rastreio = resumo.get("sem_rastreio") or []
    if sem_rastreio:
        st.error(
            "**O banco diz que mandou e o ManyChat não confirmou** nas etapas: "
            + ", ".join(f"`{e}`" for e in sem_rastreio)
            + ". Ou o tijolo de Solicitação Externa saiu do fluxo, ou o fluxo não "
            "rodou — e nesse segundo caso a mensagem não chegou em ninguém."
        )

    erros_convite = resumo.get("convites_erro", 0)
    if erros_convite:
        st.warning(f"{_br(erros_convite)} convite(s) em erro na fase das 09h — veja a tabela no fim da aba.")

    st.divider()

    if funil.empty:
        st.info("Nenhuma etapa cadastrada em `convites_aula_etapas`.")
        return

    # ── Funil do dia ─────────────────────────────────────────────────────────
    st.subheader("Grade do dia")

    rotulos = [f"{r['hora']} · {r['etapa']}" for _, r in funil.iterrows()]
    fig = go.Figure(go.Funnel(
        y=rotulos,
        x=funil["enviadas"].tolist(),
        textinfo="value+percent initial",
        marker={"color": PIX},
    ))
    grafico(fig, altura=330)
    st.plotly_chart(fig, use_container_width=True)

    tabela = funil.assign(
        Etapa=funil["etapa"],
        Hora=funil["hora"],
        Template=funil["template"],
        Enviadas=funil["enviadas"].map(_br),
        Erros=funil["erros"].map(_br),
        Cobertura=funil["cobertura"].map(lambda v: f"{v:.1f}%"),
        Status=[
            "🟢 no ar" if (r["ativa"] and r["configurada"]) else
            ("⚪ desligada" if not r["ativa"] else "🟠 sem fluxo")
            for _, r in funil.iterrows()
        ],
    )[["Etapa", "Hora", "Template", "Status", "Enviadas", "Erros", "Cobertura"]]
    st.dataframe(tabela, use_container_width=True, hide_index=True)

    # ── Dupla checagem: banco × ManyChat ─────────────────────────────────────
    st.subheader("Dupla checagem")
    st.caption(
        "**Enviadas** é o nosso banco: o ManyChat aceitou o `sendFlow`. "
        "**Confirmadas** é o próprio ManyChat avisando, de dentro do fluxo, que "
        "ele rodou pra aquela pessoa — testemunha independente do disparo. As "
        "duas colunas existem porque 'enviada' já mentiu: em 30/08 o disparo "
        "respondeu 200 com o contato sem opt-in no canal, e o WhatsApp não "
        "entregou nada. Coluna da direita muito abaixo da esquerda é alarme."
    )

    checagem = pd.DataFrame([{
        "Etapa": r["etapa"],
        "Hora": r["hora"],
        "Enviadas (banco)": _br(r["enviadas"]),
        "Confirmadas (ManyChat)": _br(r["confirmadas"]),
        "Confere": f"{r['confere']:.0f}%" if r["enviadas"] else "—",
        # Nas duas primeiras o botão é link: a pessoa sai do WhatsApp e o
        # ManyChat não vê o clique. Zero ali seria mentira, então nem mostra.
        "Cliques": _br(r["cliques"]) if r["mede_clique"] else "não dá pra medir",
        "Bloquearam": _br(r["bloqueios"]),
    } for _, r in funil.iterrows()])
    st.dataframe(checagem, use_container_width=True, hide_index=True)

    # ── Série por dia ────────────────────────────────────────────────────────
    if not por_dia.empty and por_dia["aula_data"].nunique() > 1:
        st.subheader("Por dia de aula")
        pivot = por_dia.pivot_table(
            index="aula_data", columns="etapa", values="enviadas", aggfunc="sum", fill_value=0
        )
        ordem = [e for e in funil["etapa"].tolist() if e in pivot.columns]
        st.bar_chart(pivot[ordem])

    # ── Copy de cada etapa (vive no banco) ───────────────────────────────────
    with st.expander("Copy de cada etapa (editável no banco, sem tocar no ManyChat)"):
        st.caption(
            "Os textos vão pros campos `p1`/`p2` do contato logo antes do disparo — "
            "são eles que formam o corpo dos templates aprovados. `{link}` vira o "
            "link da sala daquela pessoa."
        )
        if not etapas.empty:
            st.dataframe(
                etapas[["etapa", "hora_brt", "template", "texto_p1", "texto_p2", "flow_ns"]],
                use_container_width=True, hide_index=True,
            )

    # ── Erros ────────────────────────────────────────────────────────────────
    envios: pd.DataFrame = data.get("envios", pd.DataFrame())
    falhas = []
    if not envios.empty:
        falhas.append(envios[envios["status"] == "erro"][["aula_data", "etapa", "tentativas", "erro"]])
    if not convites.empty and (convites["status"] == "erro").any():
        c = convites[convites["status"] == "erro"].copy()
        c["etapa"] = "e_hoje (criação do contato)"
        falhas.append(c[["aula_data", "etapa", "tentativas", "erro"]])

    if falhas:
        todas = pd.concat(falhas, ignore_index=True)
        if not todas.empty:
            with st.expander(f"Erros de envio ({_br(len(todas))})"):
                st.dataframe(todas, use_container_width=True, hide_index=True)
