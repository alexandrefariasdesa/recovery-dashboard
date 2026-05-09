import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

_TRIGGERS = {"boleto_expirado", "pix_expirado", "carrinho_abandonado"}
_GENERATED = {"boleto_gerado", "pix_gerado"}
_LABELS = {
    "boleto_gerado": "Boleto Gerado",
    "boleto_expirado": "Boleto Expirado",
    "pix_gerado": "PIX Gerado",
    "pix_expirado": "PIX Expirado",
    "carrinho_abandonado": "Carrinho Abandonado",
}


def render_recovery_tab(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.info("Nenhum dado de recuperação encontrado para o período selecionado.")
        return

    triggers = df[df["tipo"].isin(_TRIGGERS)]
    generated = df[df["tipo"].isin(_GENERATED)]

    total_gerados = len(generated)
    total_triggers = len(triggers)
    total_convertidos = int(triggers["converteu"].sum()) if not triggers.empty else 0
    taxa = (total_convertidos / total_triggers * 100) if total_triggers > 0 else 0.0
    receita = triggers.loc[triggers["converteu"], "valor_recuperado"].sum() if not triggers.empty else 0.0

    # ── Métricas principais ──────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Pagamentos Gerados", total_gerados)
    c2.metric("Recuperações Disparadas", total_triggers)
    c3.metric("Convertidos", total_convertidos)
    c4.metric("Taxa de Recuperação", f"{taxa:.1f}%")
    c5.metric("Receita Recuperada", f"R$ {receita:,.2f}")

    st.divider()

    col_left, col_right = st.columns(2)

    # ── Funil ────────────────────────────────────────────────────────────────
    with col_left:
        st.subheader("Funil de Recuperação")
        fig = go.Figure(go.Funnel(
            y=["Pagamentos Gerados", "Recuperações Disparadas", "Convertidos"],
            x=[total_gerados, total_triggers, total_convertidos],
            textinfo="value+percent initial",
            marker={"color": ["#636EFA", "#EF553B", "#00CC96"]},
        ))
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=320)
        st.plotly_chart(fig, use_container_width=True)

    # ── Breakdown por tipo ───────────────────────────────────────────────────
    with col_right:
        st.subheader("Conversão por Tipo")
        rows = []
        for tipo in ["boleto_expirado", "pix_expirado", "carrinho_abandonado"]:
            subset = triggers[triggers["tipo"] == tipo] if not triggers.empty else pd.DataFrame()
            if subset.empty:
                continue
            sent = len(subset)
            conv = int(subset["converteu"].sum())
            rate = (conv / sent * 100) if sent > 0 else 0.0
            rev = subset.loc[subset["converteu"], "valor_recuperado"].sum()
            rows.append({
                "Tipo": _LABELS[tipo],
                "Disparados": sent,
                "Convertidos": conv,
                "Taxa (%)": round(rate, 1),
                "Receita (R$)": round(rev, 2),
            })

        if rows:
            bdf = pd.DataFrame(rows)
            fig2 = px.bar(
                bdf, x="Tipo", y=["Disparados", "Convertidos"],
                barmode="group",
                color_discrete_sequence=["#636EFA", "#00CC96"],
                labels={"value": "Quantidade", "variable": ""},
            )
            fig2.update_layout(legend_title_text="", margin=dict(l=0, r=0, t=10, b=0), height=320)
            st.plotly_chart(fig2, use_container_width=True)

    # ── Tabela de breakdown ──────────────────────────────────────────────────
    if rows:
        st.subheader("Detalhamento por Tipo")
        st.dataframe(
            pd.DataFrame(rows).style.format({
                "Taxa (%)": "{:.1f}%",
                "Receita (R$)": "R$ {:,.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── Tabela completa ──────────────────────────────────────────────────────
    st.subheader("Base Completa de Recuperações")

    display = df.copy()
    display["Status"] = display.apply(
        lambda r: "✅ Converteu" if r.get("converteu") else (
            "⏳ Aguardando" if r.get("tipo") in _TRIGGERS else "—"
        ), axis=1
    )
    display["Tipo"] = display["tipo"].map(_LABELS).fillna(display["tipo"])
    display["Valor"] = display["valor"].apply(lambda x: f"R$ {x:,.2f}")
    display["Recuperado"] = display["valor_recuperado"].apply(
        lambda x: f"R$ {x:,.2f}" if x > 0 else "—"
    )

    col_map = {
        "nome": "Nome", "telefone": "Telefone", "Tipo": "Tipo",
        "Valor": "Valor Original", "Status": "Status",
        "Recuperado": "Valor Recuperado", "data_pagamento": "Data Pagamento",
    }
    cols = [c for c in col_map if c in display.columns]
    st.dataframe(
        display[cols].rename(columns=col_map),
        use_container_width=True,
        hide_index=True,
    )
