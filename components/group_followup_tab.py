import streamlit as st
import pandas as pd
import plotly.graph_objects as go


def render_group_followup_tab(df: pd.DataFrame, cutoff_date) -> None:
    st.caption(
        "Quem comprou (qualquer produto), já passou de 1 dia e **ainda não entrou no grupo** — "
        f"alvo da 2ª chamada. Corte: compras a partir de **{cutoff_date.strftime('%d/%m/%Y')}**."
    )

    if df is None or df.empty:
        st.info("Nenhuma compra encontrada no período/corte selecionado.")
        return

    # Métricas do topo respeitam o corte (só compras a partir de cutoff_date)
    dfc = df[df["compra_em"].dt.date >= cutoff_date]
    total = len(dfc)
    no_grupo = int(dfc["entrou_no_grupo"].sum())
    fora_grupo = total - no_grupo
    pendentes = int(df["pendente_2a_chamada"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Compradores (no corte)", total)
    c2.metric("Já no grupo", no_grupo)
    c3.metric("Fora do grupo", fora_grupo)
    c4.metric("⚠️ Pendentes 2ª chamada", pendentes)

    st.divider()

    pend = df[df["pendente_2a_chamada"]].copy()
    if pend.empty:
        st.success("Ninguém pendente de 2ª chamada agora. 🎉")
        return

    # ── Pendentes por dia de compra ──────────────────────────────────────────
    st.subheader("Pendentes por dia de compra")
    by_day = (
        pend.assign(dia=pend["compra_em"].dt.date)
        .groupby("dia").size().reset_index(name="qtd").sort_values("dia")
    )
    fig = go.Figure(go.Bar(
        x=by_day["dia"], y=by_day["qtd"], marker_color="#EF553B",
        text=by_day["qtd"], textposition="outside",
    ))
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300,
                      yaxis_title="Pendentes", xaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Lista + export ─────────────────────────────────────────────────────────
    st.subheader("Lista para 2ª chamada")

    display = pend.copy()
    display["Valor"] = display["valor"].apply(lambda x: f"R$ {x:,.2f}")
    col_map = {
        "nome": "Nome",
        "telefone": "Telefone",
        "email": "Email",
        "produto": "Produto",
        "Valor": "Valor",
        "compra_em": "Data Compra",
        "dias_desde_compra": "Dias desde a compra",
    }
    cols = [c for c in col_map if c in display.columns]
    st.dataframe(
        display[cols].rename(columns=col_map),
        use_container_width=True,
        hide_index=True,
    )

    export_cols = [c for c in ["nome", "telefone", "email", "produto", "valor",
                               "compra_em", "dias_desde_compra"] if c in pend.columns]
    csv = pend[export_cols].to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Baixar CSV (pendentes)",
        data=csv,
        file_name="pendentes_2a_chamada_grupo.csv",
        mime="text/csv",
    )
