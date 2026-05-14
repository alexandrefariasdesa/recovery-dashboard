import streamlit as st
from datetime import datetime, timedelta, date

from processors.recovery import build_recovery_dataframe
from processors.upsell import build_upsell_dataframe
from components.recovery_tab import render_recovery_tab
from components.upsell_tab import render_upsell_tab

st.set_page_config(
    page_title="Dashboard de Recuperação & Upsell",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Dashboard de Recuperação & Upsell")

# ── Filtros de período ───────────────────────────────────────────────────────
hoje = datetime.now().date()

with st.container():
    col_atalho, col_start, col_end, col_btn = st.columns([3, 2, 2, 1])

    with col_atalho:
        atalho = st.selectbox(
            "Período rápido",
            options=[
                "Personalizado",
                "Hoje",
                "Ontem",
                "Últimos 7 dias",
                "Últimos 15 dias",
                "Últimos 30 dias",
                "Este mês",
            ],
            index=4,
            label_visibility="visible",
        )

    # Calcula datas conforme atalho
    if atalho == "Hoje":
        default_start, default_end = hoje, hoje
    elif atalho == "Ontem":
        default_start = hoje - timedelta(days=1)
        default_end = hoje - timedelta(days=1)
    elif atalho == "Últimos 7 dias":
        default_start = hoje - timedelta(days=6)
        default_end = hoje
    elif atalho == "Últimos 15 dias":
        default_start = hoje - timedelta(days=14)
        default_end = hoje
    elif atalho == "Últimos 30 dias":
        default_start = hoje - timedelta(days=29)
        default_end = hoje
    elif atalho == "Este mês":
        default_start = hoje.replace(day=1)
        default_end = hoje
    else:
        default_start = hoje - timedelta(days=14)
        default_end = hoje

    with col_start:
        start_date: date = st.date_input(
            "Data inicial",
            value=default_start,
            max_value=hoje,
            format="DD/MM/YYYY",
        )
    with col_end:
        end_date: date = st.date_input(
            "Data final",
            value=default_end,
            max_value=hoje,
            format="DD/MM/YYYY",
        )
    with col_btn:
        st.write("")
        if st.button("🔄 Atualizar", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

if start_date > end_date:
    st.error("A data inicial não pode ser maior que a data final.")
    st.stop()

st.caption(f"Período: **{start_date.strftime('%d/%m/%Y')}** até **{end_date.strftime('%d/%m/%Y')}** ({(end_date - start_date).days + 1} dias)")

st.divider()

# ── Abas ─────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs([
    "🔁 Recuperações  (Boleto / PIX / Carrinho)",
    "⬆️ Conversão Upsell",
])

with tab1:
    with st.spinner("Carregando dados de recuperação..."):
        try:
            recovery_df = build_recovery_dataframe(start_date, end_date)
            render_recovery_tab(recovery_df)
        except Exception as exc:
            st.error(f"Erro ao carregar recuperações: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)

with tab2:
    with st.spinner("Carregando dados de upsell..."):
        try:
            upsell_df = build_upsell_dataframe(start_date, end_date)
            render_upsell_tab(upsell_df)
        except Exception as exc:
            st.error(f"Erro ao carregar upsell: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)
