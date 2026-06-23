import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from processors.manychat_engagement import LABELS, ALL_TIPOS

_TYPE_COLORS = {
    "pix_boleto_gerado": "#00CC96",
    "pix_boleto_expirado": "#636EFA",
    "carrinho_abandonado": "#AB63FA",
    "compra_aprovada": "#19D3F3",
}


def render_manychat_tab(data: dict) -> None:
    resumo: pd.DataFrame = data.get("resumo", pd.DataFrame())
    diario: pd.DataFrame = data.get("diario", pd.DataFrame())

    if resumo is None or resumo.empty:
        st.info(
            "Nenhum dado de efetividade do ManyChat ainda. Confirme que o "
            "Worker está gravando na aba `cliques_manychat` e que há disparos "
            "no período."
        )
        return

    st.caption(
        "Funil: **Disparos** (mensagens enviadas) → **Recebeu** (pessoas distintas, "
        "proxy: 1 disparo ≈ 1 mensagem) → **Clicou** (cliques no botão registrados) → "
        "**Converteu pós-clique** (quem clicou e tem compra no mesmo dia ou depois). "
        "CTR = clicou ÷ recebeu."
    )

    # ── Totais (na ordem do funil) ───────────────────────────────────────────
    tot_disp = int(resumo["Disparos"].sum())
    tot_rec = int(resumo["Recebeu (pessoas)"].sum())
    tot_clk = int(resumo["Clicou (pessoas)"].sum())
    tot_conv = int(resumo["Converteu pós-clique"].sum())
    ctr_geral = (tot_clk / tot_rec * 100) if tot_rec else 0.0

    def _br(n):
        return f"{n:,}".replace(",", ".")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Disparos", _br(tot_disp))
    c2.metric("Receberam (pessoas)", _br(tot_rec))
    c3.metric("Clicaram (pessoas)", _br(tot_clk))
    c4.metric("CTR Geral", f"{ctr_geral:.1f}%")
    c5.metric("Converteram pós-clique", _br(tot_conv))

    st.divider()

    # ── Funil geral (Disparos → Recebeu → Clicou → Converteu) ────────────────
    st.subheader("Funil Geral")
    fun_opts = ["Todos (geral)"] + resumo["Tipo"].tolist()
    escolha = st.selectbox("Escolha o funil", fun_opts, index=0, key="mc_funil_sel")

    if escolha == "Todos (geral)":
        fx = [tot_disp, tot_rec, tot_clk, tot_conv]
    else:
        r = resumo[resumo["Tipo"] == escolha].iloc[0]
        fx = [
            int(r["Disparos"]),
            int(r["Recebeu (pessoas)"]),
            int(r["Clicou (pessoas)"]),
            int(r["Converteu pós-clique"]),
        ]

    fig_fun = go.Figure(go.Funnel(
        y=["Disparos", "Recebeu", "Clicou", "Converteu pós-clique"],
        x=fx,
        textinfo="value+percent initial",
        marker={"color": ["#AB63FA", "#636EFA", "#00CC96", "#19D3F3"]},
    ))
    fig_fun.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
    st.plotly_chart(fig_fun, use_container_width=True)

    st.divider()

    # ── Tabela + barras por tipo ─────────────────────────────────────────────
    st.subheader("Efetividade por Tipo de Mensagem")

    col_l, col_r = st.columns(2)
    with col_l:
        fig = px.bar(
            resumo, x="Tipo",
            y=["Disparos", "Recebeu (pessoas)", "Clicou (pessoas)"],
            barmode="group",
            color_discrete_sequence=["#AB63FA", "#636EFA", "#00CC96"],
            labels={"value": "Quantidade", "variable": ""},
            text_auto=True,
        )
        fig.update_layout(legend_title_text="", margin=dict(l=0, r=0, t=10, b=0), height=340)
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        show = resumo.drop(columns=["tipo"])
        st.dataframe(
            show.style.format({
                "CTR (%)": "{:.1f}%",
                "Conv. do clique (%)": "{:.1f}%",
            }),
            use_container_width=True,
            hide_index=True,
            height=340,
        )

    # ── CTR por tipo (barra horizontal) ──────────────────────────────────────
    st.markdown("**CTR (%) por tipo**")
    ctr_df = resumo.sort_values("CTR (%)", ascending=True)
    fig_ctr = go.Figure(go.Bar(
        x=ctr_df["CTR (%)"], y=ctr_df["Tipo"],
        orientation="h",
        marker_color=[_TYPE_COLORS.get(t, "#888") for t in ctr_df["tipo"]],
        text=[f"{v:.1f}%" for v in ctr_df["CTR (%)"]],
        textposition="outside",
    ))
    fig_ctr.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=300,
        xaxis=dict(title="CTR (%)", ticksuffix="%", rangemode="tozero"),
    )
    st.plotly_chart(fig_ctr, use_container_width=True)

    st.divider()

    # ── Diário ───────────────────────────────────────────────────────────────
    if diario is not None and not diario.empty:
        st.subheader("Cliques vs Recebidos — dia a dia")

        st.markdown("**Cliques por tipo (volume)**")
        fig_d = go.Figure()
        for tipo in ALL_TIPOS:
            sub = diario[diario["tipo"] == tipo]
            if sub.empty or sub["cliques"].sum() == 0:
                continue
            fig_d.add_trace(go.Scatter(
                x=sub["dia"], y=sub["cliques"], mode="lines+markers",
                name=LABELS.get(tipo, tipo),
                line=dict(color=_TYPE_COLORS.get(tipo), width=3),
                marker=dict(size=7),
            ))
        fig_d.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), height=320,
            yaxis=dict(title="Cliques", rangemode="tozero"),
            xaxis=dict(title=""), legend_title_text="",
        )
        st.plotly_chart(fig_d, use_container_width=True)

        # ── Taxa de clique (CTR %) por dia por tipo ──────────────────────────
        st.markdown("**Taxa de clique (CTR %) por tipo, dia a dia**")
        fig_ctr_d = go.Figure()
        for tipo in ALL_TIPOS:
            sub = diario[(diario["tipo"] == tipo) & (diario["recebidos"] > 0)]
            if sub.empty:
                continue
            fig_ctr_d.add_trace(go.Scatter(
                x=sub["dia"], y=sub["ctr"], mode="lines+markers",
                name=LABELS.get(tipo, tipo),
                line=dict(color=_TYPE_COLORS.get(tipo), width=3),
                marker=dict(size=7),
                hovertemplate=(
                    f"{LABELS.get(tipo, tipo)}<br>%{{x|%d/%m}}<br>"
                    "CTR: %{y:.1f}%<extra></extra>"
                ),
            ))
        fig_ctr_d.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), height=320,
            yaxis=dict(title="CTR (%)", ticksuffix="%", rangemode="tozero"),
            xaxis=dict(title=""), legend_title_text="",
        )
        st.plotly_chart(fig_ctr_d, use_container_width=True)
        st.caption(
            "CTR diário = cliques do dia ÷ recebidos do dia. Como o clique pode "
            "vir horas/dias depois da mensagem, leia como tendência — não como "
            "taxa exata por coorte de envio."
        )

        ddf = diario.copy()
        ddf["Tipo"] = ddf["tipo"].map(LABELS).fillna(ddf["tipo"])
        ddf["Dia"] = pd.to_datetime(ddf["dia"]).dt.strftime("%d/%m/%Y")
        ddf = ddf.rename(columns={
            "recebidos": "Recebidos", "cliques": "Cliques", "ctr": "CTR (%)",
        })[["Dia", "Tipo", "Recebidos", "Cliques", "CTR (%)"]]
        st.dataframe(
            ddf.style.format({"CTR (%)": "{:.1f}%"}),
            use_container_width=True, hide_index=True,
        )
