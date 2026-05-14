import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

_LABELS = {
    "boleto_gerado": "Boleto Gerado",
    "boleto_expirado": "Boleto Expirado",
    "pix_gerado": "PIX Gerado",
    "pix_expirado": "PIX Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
}

_TYPE_ORDER = [
    "pix_gerado", "pix_expirado",
    "boleto_gerado", "boleto_expirado",
    "carrinho_abandonado",
]


def render_recovery_tab(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("Nenhum dado de recuperação encontrado para o período selecionado.")
        return

    total = len(df)
    total_convertidos = int(df["converteu"].sum())
    taxa = (total_convertidos / total * 100) if total > 0 else 0.0
    receita_recuperavel = df.loc[~df["converteu"], "valor"].sum()
    receita_recuperada = df.loc[df["converteu"], "valor_recuperado"].sum()

    # ── Métricas principais ──────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total de Eventos", total)
    c2.metric("Converteram em Compra", total_convertidos)
    c3.metric("Taxa de Conversão Geral", f"{taxa:.1f}%")
    c4.metric("Receita Recuperável", f"R$ {receita_recuperavel:,.2f}")
    c5.metric("Receita Recuperada", f"R$ {receita_recuperada:,.2f}")

    st.divider()

    # ── Breakdown por tipo ───────────────────────────────────────────────────
    st.subheader("Conversão por Tipo de Evento")

    rows = []
    for tipo in _TYPE_ORDER:
        subset = df[df["tipo"] == tipo]
        if subset.empty:
            continue
        total_tipo = len(subset)
        conv = int(subset["converteu"].sum())
        rate = (conv / total_tipo * 100) if total_tipo > 0 else 0.0
        recuperavel = subset.loc[~subset["converteu"], "valor"].sum()
        recuperada = subset.loc[subset["converteu"], "valor_recuperado"].sum()
        rows.append({
            "Tipo": _LABELS.get(tipo, tipo),
            "Total": total_tipo,
            "Convertidos": conv,
            "Taxa (%)": round(rate, 1),
            "Receita Recuperável (R$)": round(recuperavel, 2),
            "Receita Recuperada (R$)": round(recuperada, 2),
        })

    if rows:
        bdf = pd.DataFrame(rows)

        col_left, col_right = st.columns(2)

        with col_left:
            fig = px.bar(
                bdf, x="Tipo", y=["Total", "Convertidos"],
                barmode="group",
                color_discrete_sequence=["#636EFA", "#00CC96"],
                labels={"value": "Quantidade", "variable": ""},
                text_auto=True,
            )
            fig.update_layout(
                legend_title_text="",
                margin=dict(l=0, r=0, t=10, b=0),
                height=340,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.dataframe(
                bdf.style.format({
                    "Taxa (%)": "{:.1f}%",
                    "Receita Recuperável (R$)": "R$ {:,.2f}",
                    "Receita Recuperada (R$)": "R$ {:,.2f}",
                }),
                use_container_width=True,
                hide_index=True,
                height=340,
            )

    st.divider()

    # ── Funil geral ──────────────────────────────────────────────────────────
    st.subheader("Funil Geral")
    fig_funnel = go.Figure(go.Funnel(
        y=["Total de Eventos", "Converteram em Compra"],
        x=[total, total_convertidos],
        textinfo="value+percent initial",
        marker={"color": ["#636EFA", "#00CC96"]},
    ))
    fig_funnel.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=260)
    st.plotly_chart(fig_funnel, use_container_width=True)

    st.divider()

    # ── Tabela completa ──────────────────────────────────────────────────────
    st.subheader("Base Completa de Eventos")

    display = df.copy()
    display["Status"] = display["converteu"].map(
        {True: "✅ Converteu", False: "❌ Não converteu"}
    )
    display["Tipo"] = display["tipo"].map(_LABELS).fillna(display["tipo"])
    display["Valor"] = display["valor"].apply(lambda x: f"R$ {x:,.2f}")
    display["Recuperado"] = display["valor_recuperado"].apply(
        lambda x: f"R$ {x:,.2f}" if x > 0 else "—"
    )

    col_map = {
        "nome": "Nome",
        "telefone": "Telefone",
        "Tipo": "Tipo",
        "Valor": "Valor Original",
        "Status": "Status",
        "produto_comprado": "Produto Comprado",
        "Recuperado": "Valor Recuperado",
        "data_pagamento": "Data Pagamento",
    }
    cols = [c for c in col_map if c in display.columns]
    st.dataframe(
        display[cols].rename(columns=col_map),
        use_container_width=True,
        hide_index=True,
    )
