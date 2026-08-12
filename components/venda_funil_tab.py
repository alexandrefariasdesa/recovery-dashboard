import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from processors.venda_funil import BRACOS, BRACO_LABEL, SUB_ETAPAS, SUB_LABEL


def _br(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _pct(parte: int, todo: int) -> str:
    return f"{(parte / todo * 100):.1f}%" if todo else "0.0%"


def render_venda_funil_tab(data: dict) -> None:
    geral: dict = data.get("geral", {})
    bracos: dict = data.get("bracos", {})
    tabela: pd.DataFrame = data.get("tabela", pd.DataFrame())

    recebeu = int(geral.get("recebeu", 0))
    clicou = int(geral.get("clicou", 0))

    if recebeu == 0 and clicou == 0 and (tabela is None or tabela.empty):
        st.info(
            "Nenhum evento do fluxo `disparo_venda` ainda. Confirme que os "
            "tijolos de External Request estão configurados no fluxo do "
            "ManyChat e que o Worker `recovery-flow-tracker` está no ar."
        )
        return

    st.caption(
        "Funil do **disparo via API pra venda de produto**, medido dentro do "
        "ManyChat: **Recebeu** → **Clicou** → escolha entre **Calculando** ou "
        "**Sentindo** → **Respondeu** → **Pitch 1 → 2 → 3** em cada braço. "
        "Pessoas distintas por etapa (subscriber_id, fallback telefone)."
    )

    # ── Topo do funil (comum aos 2 braços) ──────────────────────────────────
    escolheu_calc = int(bracos.get("calculando", {}).get("escolheu", 0))
    escolheu_sent = int(bracos.get("sentindo", {}).get("escolheu", 0))
    escolheram = escolheu_calc + escolheu_sent

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Receberam", _br(recebeu))
    c2.metric("Clicaram na 1ª msg", _br(clicou), _pct(clicou, recebeu))
    c3.metric("🧮 Calculando", _br(escolheu_calc), _pct(escolheu_calc, clicou))
    c4.metric("💗 Sentindo", _br(escolheu_sent), _pct(escolheu_sent, clicou))
    st.caption(
        "Delta = taxa sobre a etapa anterior (Clicou÷Recebeu · Escolheu÷Clicou). "
        f"Escolheram uma opção: **{_br(escolheram)}** ({_pct(escolheram, clicou)} de quem clicou)."
    )

    st.divider()

    # ── Funil dos 2 braços lado a lado ──────────────────────────────────────
    st.subheader("Funil por opção")
    cores = {"calculando": "#636EFA", "sentindo": "#EF553B"}
    col_calc, col_sent = st.columns(2)
    for braco, col in zip(BRACOS, [col_calc, col_sent]):
        b = bracos.get(braco, {})
        etapas_y = ["Escolheu"] + [SUB_LABEL[s] for s in SUB_ETAPAS]
        valores = [int(b.get("escolheu", 0))] + [int(b.get(s, 0)) for s in SUB_ETAPAS]
        with col:
            st.markdown(f"**{BRACO_LABEL[braco]}**")
            fig = go.Figure(go.Funnel(
                y=etapas_y,
                x=valores,
                textinfo="value+percent initial",
                marker={"color": cores[braco]},
            ))
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=320)
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Tabela comparativa ───────────────────────────────────────────────────
    st.subheader("Comparativo Calculando × Sentindo")
    if tabela is not None and not tabela.empty:
        show = tabela.drop(columns=["braco"])
        fmt = {c: "{:.1f}%" for c in show.columns if c.endswith("(%)")}
        st.dataframe(
            show.style.format(fmt),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Cada % é sobre a etapa anterior do próprio braço "
            "(Respondeu÷Escolheu · Pitch 1÷Respondeu · ...). "
            "'Funil total' = Pitch 3 ÷ Escolheu."
        )

    # ── Referência das etapas rastreadas ─────────────────────────────────────
    with st.expander("🔗 Etapas rastreadas (referência pros tijolos do ManyChat)"):
        st.markdown(
            "Cada etapa é um tijolo **External Request (POST)** no fluxo, "
            "apontando pro Worker `recovery-flow-tracker` com "
            "`?fluxo=disparo_venda&etapa=<slug>` na URL e corpo "
            "**Full Contact Data**. Slugs válidos:\n\n"
            "| Momento no fluxo | `&etapa=` |\n"
            "|---|---|\n"
            "| Recebeu a 1ª mensagem | `recebeu` |\n"
            "| Clicou na 1ª mensagem | `clicou` |\n"
            "| Escolheu a opção Calculando | `calculando` |\n"
            "| Escolheu a opção Sentindo | `sentindo` |\n"
            "| Respondeu (braço Calculando) | `calculando_respondeu` |\n"
            "| Pitch 1/2/3 (braço Calculando) | `calculando_pitch_1` `calculando_pitch_2` `calculando_pitch_3` |\n"
            "| Respondeu (braço Sentindo) | `sentindo_respondeu` |\n"
            "| Pitch 1/2/3 (braço Sentindo) | `sentindo_pitch_1` `sentindo_pitch_2` `sentindo_pitch_3` |\n"
        )
