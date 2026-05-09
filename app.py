import streamlit as st
from datetime import datetime, timedelta

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

# ── Filtros globais ──────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    start_date = st.date_input(
        "Data inicial",
        value=datetime.now().date() - timedelta(days=30),
        max_value=datetime.now().date(),
    )
with col2:
    end_date = st.date_input(
        "Data final",
        value=datetime.now().date(),
        max_value=datetime.now().date(),
    )
with col3:
    st.write("")
    if st.button("🔄 Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if start_date > end_date:
    st.error("A data inicial não pode ser maior que a data final.")
    st.stop()

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
