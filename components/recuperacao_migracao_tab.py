import streamlit as st
import pandas as pd


def _br(n) -> str:
    return f"{int(n):,}".replace(",", ".")


_MODO_LABEL = {
    "off": "⚪ desligado",
    "simulado": "🧪 simulado (não manda nada)",
    "teste": "🟡 teste (só a whitelist recebe)",
    "ligado": "🟢 ligado",
}


def render_recuperacao_migracao_tab(data: dict) -> None:
    resumo: dict = data.get("resumo", {})
    config: pd.DataFrame = data.get("config", pd.DataFrame())
    etapas: pd.DataFrame = data.get("etapas", pd.DataFrame())
    testes: pd.DataFrame = data.get("testes", pd.DataFrame())
    disparos: pd.DataFrame = data.get("disparos", pd.DataFrame())
    quadro: pd.DataFrame = data.get("quadro", pd.DataFrame())

    st.caption(
        "Motor próprio de recuperação — a migração do **Make** pra dentro do Supabase. "
        "O `payt-webhook` já grava os eventos; um cron de 5 em 5 minutos monta a escada "
        "de mensagens de cada evento e drena o que venceu, chamando a API do ManyChat "
        "direto. Enquanto o modo for **simulado**, nada é enviado: o disparo fica "
        "registrado com o texto que teria ido — é assim que dá pra rodar junto do Make "
        "e comparar antes de virar a chave."
    )

    modos = resumo.get("modos", {})
    if modos and all(m == "simulado" for m in modos.values()):
        st.info("Todos os tipos estão em **simulado** — o Make continua sendo quem fala com o cliente.")
    elif any(m == "ligado" for m in modos.values()):
        st.warning(
            "Tipos em **ligado** disparam de verdade: "
            + ", ".join(f"`{t}`" for t, m in modos.items() if m == "ligado")
            + ". Confirme que o Make foi desligado pra esses, senão a pessoa recebe duas vezes."
        )

    sem_fluxo = resumo.get("sem_fluxo") or []
    if sem_fluxo:
        st.warning(
            "Etapas ativas sem fluxo do ManyChat (vão dar erro se sair do simulado): "
            + ", ".join(f"`{e}`" for e in sem_fluxo)
            + " — grave o `ns` em `recuperacao_etapas.flow_ns`."
        )

    # ── Números de topo ──────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Disparos na fila", _br(resumo.get("total", 0)))
    c2.metric("Mandaria / mandou", _br(resumo.get("resolvidos", 0)))
    c3.metric("Ainda agendados", _br(resumo.get("agendados", 0)))
    c4.metric(
        "Cortados por compra",
        _br(resumo.get("cancelados", 0)),
        help="Supressão: a pessoa comprou depois do evento, então o resto da escada foi cancelado.",
    )
    c5.metric("Erros", _br(resumo.get("erros", 0)))

    st.caption(
        f"Supressão pegou **{resumo.get('taxa_supressao', 0.0):.1f}%** dos disparos do período — "
        "é o que evita cobrar quem já pagou."
    )

    st.divider()

    # ── Modo de cada tipo ────────────────────────────────────────────────────
    st.subheader("Modo por tipo de evento")
    if not config.empty:
        vis = config.assign(
            Tipo=config["tipo"],
            Nasce_de=config["origem"].map(
                {"evento": "evento (PIX/boleto/carrinho)", "compra": "compra aprovada"}
            ).fillna(config["origem"]),
            Modo=config["modo"].map(lambda m: _MODO_LABEL.get(m, m)),
            **{"Agenda a partir de": config["desde"]},
        ).rename(columns={"Nasce_de": "Nasce de"})[
            ["Tipo", "Nasce de", "Modo", "Agenda a partir de"]
        ]
        st.dataframe(vis, use_container_width=True, hide_index=True)
    st.caption(
        "Pra virar a chave de um tipo: "
        "`update recuperacao_config set modo = 'ligado' where tipo = 'pix_expirado';` — "
        "e desligue o cenário correspondente no Make no mesmo movimento."
    )

    if not quadro.empty:
        st.subheader("Disparos por tipo e status")
        st.dataframe(quadro, use_container_width=True, hide_index=True)

    # ── O que teria sido enviado ─────────────────────────────────────────────
    st.subheader("O que o motor mandaria")
    if disparos.empty:
        st.info("Nenhum disparo no período. Confirme que `recuperacao_config.desde` está preenchido.")
    else:
        alvo = disparos[disparos["status"].isin(["simulado", "enviado"])].copy()
        if alvo.empty:
            st.info("Nada resolvido ainda no período — os disparos ou estão agendados ou foram cortados.")
        else:
            alvo = alvo.sort_values("enviado_em", ascending=False)
            vis = alvo.assign(
                Quando=alvo["enviado_em"],
                Evento=alvo["tipo"],
                Etapa=alvo["etapa"],
                Nome=alvo["nome"],
                Valor=alvo["valor"].map(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
                Status=alvo["status"],
                Mensagem=alvo["preview"],
            )[["Quando", "Evento", "Etapa", "Nome", "Valor", "Status", "Mensagem"]]
            st.dataframe(vis, use_container_width=True, hide_index=True)

    # ── Escada e whitelist ───────────────────────────────────────────────────
    with st.expander("Escada de mensagens (atraso, template e copy de cada etapa)"):
        st.caption(
            "`atraso` conta a partir do evento. `{nome}` e `{valor}` são trocados pelos "
            "dados da pessoa. Acrescentar uma repescagem é um insert em `recuperacao_etapas`."
        )
        if not etapas.empty:
            st.dataframe(etapas, use_container_width=True, hide_index=True)

    with st.expander(f"Telefones de teste ({_br(len(testes))})"):
        st.caption(
            "No modo `teste`, só estes recebem de verdade; o resto continua simulado. "
            "Inserir: `insert into recuperacao_teste_telefones (telefone_core, nome) values ('...', '...');`"
        )
        if testes.empty:
            st.info("Nenhum telefone de teste cadastrado ainda.")
        else:
            st.dataframe(testes, use_container_width=True, hide_index=True)

    # ── Erros ────────────────────────────────────────────────────────────────
    if not disparos.empty and (disparos["status"] == "erro").any():
        falhas = disparos[disparos["status"] == "erro"]
        with st.expander(f"Erros de disparo ({_br(len(falhas))})"):
            st.dataframe(
                falhas[["quando_enviar", "tipo", "etapa", "tentativas", "erro"]],
                use_container_width=True, hide_index=True,
            )
