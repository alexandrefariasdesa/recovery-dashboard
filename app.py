import streamlit as st
from datetime import datetime, timedelta, date

from processors.recovery import build_recovery_dataframe
from processors.upsell import build_upsell_dataframe
from processors.group_followup import build_group_followup_dataframe
from processors.manychat_engagement import build_manychat_engagement
from processors.manychat_funil import build_funis
from components.recovery_tab import render_recovery_tab
from components.upsell_tab import render_upsell_tab
from components.group_followup_tab import render_group_followup_tab
from components.manychat_tab import render_manychat_tab
from components.manychat_funil_tab import render_funil_tab

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
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔁 Recuperações  (Boleto / PIX / Carrinho)",
    "⬆️ Conversão Upsell",
    "👥 Grupo — 2ª chamada",
    "📣 Efetividade ManyChat",
    "🧭 Funil de Etapas ManyChat",
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

with tab3:
    # Corte padrão: início da campanha do grupo (independe do período acima)
    cutoff = st.date_input(
        "Considerar compras a partir de",
        value=date(2026, 5, 10),
        max_value=hoje,
        format="DD/MM/YYYY",
        key="grupo_cutoff",
    )
    with st.spinner("Carregando pendentes de 2ª chamada..."):
        try:
            grupo_df = build_group_followup_dataframe(hoje, cutoff)
            render_group_followup_tab(grupo_df, cutoff)
        except Exception as exc:
            st.error(f"Erro ao carregar segmento do grupo: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)

with tab4:
    with st.spinner("Carregando efetividade do ManyChat..."):
        try:
            mc_data = build_manychat_engagement(start_date, end_date)
            render_manychat_tab(mc_data)
        except Exception as exc:
            st.error(f"Erro ao carregar efetividade do ManyChat: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)

with tab5:
    with st.spinner("Carregando funil de etapas do ManyChat..."):
        try:
            funil_data = build_funis(start_date, end_date)
            render_funil_tab(funil_data)
        except Exception as exc:
            st.error(f"Erro ao carregar funil de etapas: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)
