import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import config


def render_upsell_tab(df: pd.DataFrame) -> None:
    st.caption(f"Produto rastreado: **{config.LOW_TICKET_PRODUCT}**")

    if df is None or df.empty:
        st.info(f"Nenhum comprador encontrado para '{config.LOW_TICKET_PRODUCT}' no período selecionado.")
        return

    total_compradores = len(df)
    entradas_grupo = int(df["entrou_no_grupo"].sum())
    nao_entrou = total_compradores - entradas_grupo
    taxa_conversao = (entradas_grupo / total_compradores * 100) if total_compradores > 0 else 0.0
    receita_low = df["valor"].sum()

    # ── Métricas principais ──────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compradores", total_compradores)
    c2.metric("Entraram no Grupo", entradas_grupo)
    c3.metric("Não Entraram", nao_entrou)
    c4.metric("Taxa de Entrada no Grupo", f"{taxa_conversao:.1f}%")

    st.divider()

    col_left, col_right = st.columns(2)

    # ── Funil ────────────────────────────────────────────────────────────────
    with col_left:
        st.subheader("Funil de Entrada no Grupo")
        fig_funnel = go.Figure(go.Funnel(
            y=["Compradores", "Entraram no Grupo"],
            x=[total_compradores, entradas_grupo],
            textinfo="value+percent initial",
            marker={"color": ["#636EFA", "#00CC96"]},
        ))
        fig_funnel.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
        st.plotly_chart(fig_funnel, use_container_width=True)

    # ── Pizza entrada vs não entrou ──────────────────────────────────────────
    with col_right:
        st.subheader("Entradas no Grupo")
        pie_df = pd.DataFrame({
            "Status": ["Entraram no Grupo", "Não Entraram"],
            "Quantidade": [entradas_grupo, nao_entrou],
        })
        fig_pie = px.pie(
            pie_df,
            names="Status",
            values="Quantidade",
            hole=0.4,
            color="Status",
            color_discrete_map={"Entraram no Grupo": "#00CC96", "Não Entraram": "#636EFA"},
        )
        fig_pie.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
        st.plotly_chart(fig_pie, use_container_width=True)

    # ── Evolução diária ──────────────────────────────────────────────────────
    if "compra_em" in df.columns and df["compra_em"].notna().any():
        try:
            df_time = df.copy()
            df_time["compra_em"] = pd.to_datetime(df_time["compra_em"], errors="coerce")
            df_time = df_time.dropna(subset=["compra_em"])
            df_time["data"] = df_time["compra_em"].dt.date

            daily_agg = (
                df_time.groupby("data")
                .agg(total=("entrou_no_grupo", "count"), entrou=("entrou_no_grupo", "sum"))
                .reset_index()
            )
            daily_agg["taxa"] = (daily_agg["entrou"] / daily_agg["total"] * 100).round(1)

            col_bar, col_rate = st.columns(2)

            with col_bar:
                st.subheader("Compradores por Dia")
                daily_stack = (
                    df_time.groupby(["data", "entrou_no_grupo"])
                    .size()
                    .reset_index(name="count")
                )
                daily_stack["status"] = daily_stack["entrou_no_grupo"].map(
                    {True: "Entrou no Grupo", False: "Não Entrou"}
                )
                fig_bar = px.bar(
                    daily_stack,
                    x="data",
                    y="count",
                    color="status",
                    color_discrete_map={"Entrou no Grupo": "#00CC96", "Não Entrou": "#636EFA"},
                    labels={"data": "Data", "count": "Quantidade", "status": ""},
                    text_auto=True,
                )
                fig_bar.update_layout(legend_title_text="")
                st.plotly_chart(fig_bar, use_container_width=True)

            with col_rate:
                st.subheader("Taxa de Entrada no Grupo por Dia")
                fig_rate = px.line(
                    daily_agg,
                    x="data",
                    y="taxa",
                    markers=True,
                    labels={"data": "Data", "taxa": "Taxa (%)"},
                    text="taxa",
                )
                fig_rate.update_traces(
                    line_color="#00CC96",
                    texttemplate="%{text}%",
                    textposition="top center",
                )
                fig_rate.update_layout(yaxis_ticksuffix="%", yaxis_range=[0, 100])
                st.plotly_chart(fig_rate, use_container_width=True)

        except Exception:
            pass

    st.divider()

    # ── Tabela detalhada ─────────────────────────────────────────────────────
    st.subheader("Base de Compradores")

    display = df.copy()
    display["Status Grupo"] = display["entrou_no_grupo"].map(
        {True: "✅ Entrou", False: "❌ Não entrou"}
    )
    display["Valor"] = display["valor"].apply(lambda x: f"R$ {x:,.2f}")

    col_map = {
        "nome": "Nome",
        "email": "Email",
        "telefone": "Telefone",
        "Valor": "Valor",
        "compra_em": "Data Compra",
        "payment_method": "Pagamento",
        "Status Grupo": "Entrou no Grupo",
        "data_entrada_grupo": "Data Entrada no Grupo",
    }
    cols = [c for c in col_map if c in display.columns]
    st.dataframe(
        display[cols].rename(columns=col_map),
        use_container_width=True,
        hide_index=True,
    )
