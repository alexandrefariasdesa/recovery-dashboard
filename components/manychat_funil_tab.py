import streamlit as st
import pandas as pd
import plotly.graph_objects as go

def _br(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def render_funil_tab(data: dict) -> None:
    resumo: pd.DataFrame = data.get("resumo", pd.DataFrame())

    if resumo is None or resumo.empty:
        st.info(
            "Nenhum evento de etapa ainda. Confirme que o Worker "
            "`recovery-flow-tracker` está gravando na aba `eventos_manychat` "
            "e que há tijolos configurados nos 4 fluxos do ManyChat."
        )
        return

    st.caption(
        "Funil de etapas **dentro do próprio fluxo do ManyChat** (sem cruzar "
        "com venda): **Recebeu** → **Entrou** → **Engajou**. Pessoas distintas "
        "por etapa (subscriber_id, fallback telefone). Complementar à aba "
        "'Efetividade ManyChat' — aquela mede clique→venda, esta mede o quanto "
        "a pessoa avança dentro do fluxo."
    )

    tot_rec = int(resumo["Recebeu"].sum())
    tot_ent = int(resumo["Entrou"].sum())
    tot_eng = int(resumo["Engajou"].sum())
    tx_ent = (tot_ent / tot_rec * 100) if tot_rec else 0.0
    tx_eng = (tot_eng / tot_ent * 100) if tot_ent else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("Receberam", _br(tot_rec))
    c2.metric("Entraram", _br(tot_ent), f"{tx_ent:.1f}%")
    c3.metric("Engajaram", _br(tot_eng), f"{tx_eng:.1f}%")
    st.caption("Delta de cada card = taxa sobre a etapa anterior (Entrou÷Recebeu · Engajou÷Entrou).")

    st.divider()

    st.subheader("Funil por fluxo")
    fluxo_opts = ["Todos (geral)"] + resumo["Fluxo"].tolist()
    escolha = st.selectbox("Escolha o fluxo", fluxo_opts, index=0, key="mc_funil_etapas_sel")

    if escolha == "Todos (geral)":
        fx = [tot_rec, tot_ent, tot_eng]
    else:
        r = resumo[resumo["Fluxo"] == escolha].iloc[0]
        fx = [int(r["Recebeu"]), int(r["Entrou"]), int(r["Engajou"])]

    fig_fun = go.Figure(go.Funnel(
        y=["Recebeu", "Entrou", "Engajou"],
        x=fx,
        textinfo="value+percent initial",
        marker={"color": ["#64748B", "#00A98F", "#19D3F3"]},
    ))
    fig_fun.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
    st.plotly_chart(fig_fun, use_container_width=True)

    st.divider()

    st.subheader("Todos os fluxos")
    show = resumo.drop(columns=["fluxo"])
    st.dataframe(
        show.style.format({
            "Entrada (%)": "{:.1f}%",
            "Engajamento (%)": "{:.1f}%",
            "Funil total (%)": "{:.1f}%",
        }),
        use_container_width=True,
        hide_index=True,
    )
