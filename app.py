import streamlit as st
from datetime import datetime, timedelta, date

from processors.recovery import build_recovery_dataframe
from processors.upsell import build_upsell_dataframe
from processors.group_followup import build_group_followup_dataframe
from processors.manychat_engagement import build_manychat_engagement
from processors.manychat_funil import build_funis
from processors.venda_funil import build_venda_funil
from processors.aula_convites import build_aula_convites
from processors.recuperacao_migracao import build_recuperacao_migracao
from components.recovery_tab import render_recovery_tab
from components.upsell_tab import render_upsell_tab
from components.group_followup_tab import render_group_followup_tab
from components.manychat_tab import render_manychat_tab
from components.manychat_funil_tab import render_funil_tab
from components.venda_funil_tab import render_venda_funil_tab
from components.aula_tab import render_aula_tab
from components.recuperacao_migracao_tab import render_recuperacao_migracao_tab
from components.theme import aplicar_tema, cabecalho
from components.auth import exigir_senha

st.set_page_config(
    page_title="Recuperação · painel de operação",
    page_icon="◧",
    layout="wide",
)

exigir_senha()
aplicar_tema()

# O cabeçalho precisa do período escolhido logo abaixo, mas tem que aparecer
# primeiro — reserva o lugar agora e preenche depois.
topo = st.container()

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
        st.markdown('<div class="op-espaco-rotulo"></div>', unsafe_allow_html=True)
        if st.button("Atualizar", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

if start_date > end_date:
    st.error("A data inicial não pode ser maior que a data final.")
    st.stop()

with topo:
    cabecalho(start_date, end_date)

# ── Abas ─────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Recuperações",
    "Upsell",
    "Grupo",
    "Efetividade",
    "Funil de etapas",
    "Funil de venda",
    "Convite da aula",
    "Motor novo",
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

with tab6:
    with st.spinner("Carregando funil de venda (disparo API)..."):
        try:
            venda_data = build_venda_funil(start_date, end_date)
            render_venda_funil_tab(venda_data)
        except Exception as exc:
            st.error(f"Erro ao carregar funil de venda: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)

with tab7:
    with st.spinner("Carregando convites da aula..."):
        try:
            aula_data = build_aula_convites(start_date, end_date)
            render_aula_tab(aula_data)
        except Exception as exc:
            st.error(f"Erro ao carregar convites da aula: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)

with tab8:
    with st.spinner("Carregando motor de recuperação..."):
        try:
            recup_data = build_recuperacao_migracao(start_date, end_date)
            render_recuperacao_migracao_tab(recup_data)
        except Exception as exc:
            st.error(f"Erro ao carregar motor de recuperação: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)
