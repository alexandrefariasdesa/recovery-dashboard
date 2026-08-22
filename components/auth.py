"""
components/auth.py
================================================================================
Porta de entrada do painel.

O painel mostra nome, telefone e valor de compra de cliente — no Streamlit Cloud
ele estava atrás do controle de acesso da plataforma; num serviço próprio a URL
é pública. Então: senha única em `APP_PASSWORD` (env var no Railway).

Sem `APP_PASSWORD` definida não há porta — é o modo de rodar local.
"""
import hmac
import os

import streamlit as st

from components.theme import aplicar_tema


def _senha_configurada() -> str:
    try:
        val = st.secrets.get("APP_PASSWORD")
        if val:
            return str(val)
    except Exception:
        pass
    return os.getenv("APP_PASSWORD", "")


def exigir_senha() -> None:
    """Trava a página até a senha bater. Chame logo depois do set_page_config."""
    esperada = _senha_configurada()
    if not esperada:
        return
    if st.session_state.get("_autenticado"):
        return

    aplicar_tema()
    st.markdown(
        '<div class="op-marca" style="margin-bottom:.15rem">Recuperação<em>.</em></div>'
        '<div class="op-sub" style="margin-bottom:1.4rem">Painel de operação — acesso restrito</div>',
        unsafe_allow_html=True,
    )

    with st.form("entrar"):
        senha = st.text_input("Senha", type="password", label_visibility="collapsed",
                              placeholder="Senha")
        entrou = st.form_submit_button("Entrar")

    if entrou:
        if hmac.compare_digest(senha, esperada):
            st.session_state["_autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta. Tente de novo.")

    st.stop()
