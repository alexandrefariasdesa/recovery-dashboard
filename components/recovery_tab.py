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

    # ── Recuperação dia a dia ────────────────────────────────────────────────
    st.subheader("Recuperação Dia a Dia")

    # Cores fixas por tipo (consistentes entre gráfico e legenda)
    _TYPE_COLORS = {
        "pix_gerado": "#00CC96",
        "pix_expirado": "#636EFA",
        "boleto_gerado": "#FFA15A",
        "boleto_expirado": "#EF553B",
        "carrinho_abandonado": "#AB63FA",
    }

    daily = df.copy()
    daily["dia"] = daily["evento_em"].dt.date

    grp = daily.groupby(["dia", "tipo"]).agg(
        eventos=("converteu", "size"),
        convertidos=("converteu", "sum"),
        recuperavel=("valor", "sum"),
        recuperada=("valor_recuperado", "sum"),
    ).reset_index()
    # Receita recuperável = valor dos que NÃO converteram
    nao_conv = daily[~daily["converteu"]].groupby(["dia", "tipo"])["valor"].sum()
    grp = grp.set_index(["dia", "tipo"])
    grp["recuperavel"] = nao_conv.reindex(grp.index).fillna(0.0)
    grp = grp.reset_index()
    grp["taxa"] = (grp["convertidos"] / grp["eventos"] * 100).round(1)
    grp = grp.sort_values("dia")

    # ── Linha: taxa de conversão por tipo, dia a dia ─────────────────────────
    st.markdown("**Taxa de Conversão (%) por tipo**")
    fig_taxa = go.Figure()
    for tipo in _TYPE_ORDER:
        sub = grp[grp["tipo"] == tipo]
        if sub.empty:
            continue
        fig_taxa.add_trace(go.Scatter(
            x=sub["dia"], y=sub["taxa"],
            mode="lines+markers",
            name=_LABELS.get(tipo, tipo),
            line=dict(color=_TYPE_COLORS.get(tipo), width=3),
            marker=dict(size=7),
            hovertemplate=f"{_LABELS.get(tipo, tipo)}<br>%{{x|%d/%m}}<br>Taxa: %{{y:.1f}}%<extra></extra>",
        ))
    fig_taxa.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=320,
        yaxis=dict(title="Taxa (%)", ticksuffix="%", rangemode="tozero"),
        xaxis=dict(title=""),
        legend_title_text="",
    )
    st.plotly_chart(fig_taxa, use_container_width=True)

    # ── Linhas: receita recuperável vs recuperada, dia a dia (total) ─────────
    st.markdown("**Receita Recuperável vs Recuperada por dia**")
    receita_dia = grp.groupby("dia").agg(
        recuperavel=("recuperavel", "sum"),
        recuperada=("recuperada", "sum"),
    ).reset_index().sort_values("dia")
    fig_rev = go.Figure()
    fig_rev.add_trace(go.Scatter(
        x=receita_dia["dia"], y=receita_dia["recuperavel"],
        mode="lines+markers", name="Recuperável",
        line=dict(color="#EF553B", width=3), marker=dict(size=7),
        hovertemplate="%{x|%d/%m}<br>Recuperável: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_rev.add_trace(go.Scatter(
        x=receita_dia["dia"], y=receita_dia["recuperada"],
        mode="lines+markers", name="Recuperada",
        line=dict(color="#00CC96", width=3), marker=dict(size=7),
        hovertemplate="%{x|%d/%m}<br>Recuperada: R$ %{y:,.2f}<extra></extra>",
    ))
    fig_rev.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=320,
        yaxis=dict(title="Receita (R$)", rangemode="tozero"),
        xaxis=dict(title=""),
        legend_title_text="",
    )
    st.plotly_chart(fig_rev, use_container_width=True)

    # ── Tabela detalhada: dia × tipo ─────────────────────────────────────────
    st.markdown("**Detalhamento por dia e tipo**")
    ddf = grp.copy()
    ddf["Tipo"] = ddf["tipo"].map(_LABELS).fillna(ddf["tipo"])
    ddf["Dia"] = pd.to_datetime(ddf["dia"]).dt.strftime("%d/%m/%Y")
    ddf = ddf.rename(columns={
        "eventos": "Eventos",
        "convertidos": "Convertidos",
        "taxa": "Taxa (%)",
        "recuperavel": "Receita Recuperável (R$)",
        "recuperada": "Receita Recuperada (R$)",
    })[[
        "Dia", "Tipo", "Eventos", "Convertidos", "Taxa (%)",
        "Receita Recuperável (R$)", "Receita Recuperada (R$)",
    ]]
    st.dataframe(
        ddf.style.format({
            "Taxa (%)": "{:.1f}%",
            "Receita Recuperável (R$)": "R$ {:,.2f}",
            "Receita Recuperada (R$)": "R$ {:,.2f}",
        }),
        use_container_width=True,
        hide_index=True,
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
