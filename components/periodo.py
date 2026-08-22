"""
components/periodo.py
================================================================================
O filtro de período, que é global: vale pra todas as páginas de resultado.

Mora na barra lateral, junto da navegação, por isso mesmo — um controle que
manda em todas as páginas não pode parecer parte de uma. A página de operação
ignora ele de propósito ("o que está rodando" é sempre agora), e diz isso.
"""
from datetime import date, datetime, timedelta

import streamlit as st


_ATALHOS = {
    "Hoje": lambda h: (h, h),
    "Ontem": lambda h: (h - timedelta(days=1), h - timedelta(days=1)),
    "Últimos 7 dias": lambda h: (h - timedelta(days=6), h),
    "Últimos 15 dias": lambda h: (h - timedelta(days=14), h),
    "Últimos 30 dias": lambda h: (h - timedelta(days=29), h),
    "Este mês": lambda h: (h.replace(day=1), h),
    "Personalizado": lambda h: (h - timedelta(days=14), h),
}


def seletor_periodo() -> tuple[date, date]:
    hoje = datetime.now().date()

    with st.sidebar:
        st.markdown("### Período")
        atalho = st.selectbox(
            "Período rápido",
            options=list(_ATALHOS.keys()),
            index=list(_ATALHOS.keys()).index("Últimos 15 dias"),
            label_visibility="collapsed",
        )
        ini, fim = _ATALHOS[atalho](hoje)

        col_a, col_b = st.columns(2)
        with col_a:
            # Sem `key` de propósito: com key fixa o Streamlit ignora o `value`
            # depois do primeiro render, e trocar o atalho não mexeria nas datas.
            start_date = st.date_input(
                "De", value=ini, max_value=hoje, format="DD/MM/YYYY"
            )
        with col_b:
            end_date = st.date_input(
                "Até", value=fim, max_value=hoje, format="DD/MM/YYYY"
            )

        if st.button("Atualizar dados", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    return start_date, end_date
