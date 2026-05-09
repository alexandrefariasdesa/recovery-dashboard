import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import config


def render_upsell_tab(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info(f"Nenhum comprador encontrado para '{config.LOW_TICKET_PRODUCT}' no período selecionado.")
        return

    total_compradores = len(df)
    entradas_grupo = int(df["entrou_no_grupo"].sum())
    taxa_conversao = (entradas_grupo / total_compradores * 100) if total_compradores > 0 else 0.0
    receita_low = df["valor"].sum()

    # ── Métricas principais ──────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compradores Low Ticket", total_compradores)
    c2.metric("Entraram no Grupo", entradas_grupo)
    c3.metric("Taxa de Conversão", f"{taxa_conversao:.1f}%")
    c4.metric("Receita Low Ticket", f"R$ {receita_low:,.2f}")

    st.divider()

    col_left, col_right = st.columns(2)

    # ── Funil ────────────────────────────────────────────────────────────────
    with col_left:
        st.subheader("Funil de Conversão")
        fig_funnel = go.Figure(go.Funnel(
            y=["Compradores Low Ticket", "Entraram no Grupo Upsell"],
            x=[total_compradores, entradas_grupo],
            textinfo="value+percent initial",
            marker={"color": ["#636EFA", "#00CC96"]},
        ))
        fig_funnel.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
        st.plotly_chart(fig_funnel, use_container_width=True)

    # ── Método de pagamento ──────────────────────────────────────────────────
    with col_right:
        st.subheader("Método de Pagamento")
        if "payment_method" in df.columns and df["payment_method"].notna().any():
            method_counts = (
                df["payment_method"]
                .value_counts()
                .reset_index()
                .rename(columns={"payment_method": "Método", "count": "Quantidade"})
            )
            fig_pie = px.pie(
                method_counts,
                names="Método",
                values="Quantidade",
                hole=0.4,
            )
            fig_pie.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
            st.plotly_chart(fig_pie, use_container_width=True)

    # ── Evolução diária ──────────────────────────────────────────────────────
    if "compra_em" in df.columns and df["compra_em"].notna().any():
        st.subheader("Compradores por Dia")
        try:
            df_time = df.copy()
            df_time["compra_em"] = pd.to_datetime(df_time["compra_em"], errors="coerce", utc=True)
            df_time = df_time.dropna(subset=["compra_em"])
            df_time["data"] = df_time["compra_em"].dt.date

            daily = (
                df_time.groupby(["data", "entrou_no_grupo"])
                .size()
                .reset_index(name="count")
            )
            daily["status"] = daily["entrou_no_grupo"].map(
                {True: "Entrou no Grupo", False: "Não Entrou"}
            )

            fig_time = px.bar(
                daily,
                x="data",
                y="count",
                color="status",
                color_discrete_map={"Entrou no Grupo": "#00CC96", "Não Entrou": "#636EFA"},
                labels={"data": "Data", "count": "Quantidade", "status": ""},
            )
            fig_time.update_layout(legend_title_text="")
            st.plotly_chart(fig_time, use_container_width=True)
        except Exception:
            pass

    st.divider()

    # ── Tabela detalhada ─────────────────────────────────────────────────────
    st.subheader("Base de Compradores")

    display = df.copy()
    display["Status Upsell"] = display["entrou_no_grupo"].map(
        {True: "✅ Entrou no Grupo", False: "❌ Não entrou"}
    )
    display["Valor"] = display["valor"].apply(lambda x: f"R$ {x:,.2f}")

    col_map = {
        "nome": "Nome",
        "email": "Email",
        "telefone": "Telefone",
        "Valor": "Valor",
        "compra_em": "Data Compra",
        "payment_method": "Pagamento",
        "Status Upsell": "Status Upsell",
        "data_entrada_grupo": "Entrada no Grupo",
    }
    cols = [c for c in col_map if c in display.columns]
    st.dataframe(
        display[cols].rename(columns=col_map),
        use_container_width=True,
        hide_index=True,
    )
