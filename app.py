"""
app.py — entrada do painel de operação.

Navegação em páginas (`st.navigation`), não abas. A diferença não é estética:
`st.tabs` renderiza o conteúdo de TODAS as abas em cada interação, então o
painel rodava as oito consultas pra mostrar uma. Com páginas, só a que está
aberta consulta o banco.

A ordem dos grupos é a ordem de quem chega no painel querendo saber algo:

    OPERAÇÃO    as peças estão de pé?          (não depende de período)
    RESULTADO   quanto rendeu no período?
    MANYCHAT    onde as pessoas travam no fluxo?
    MOTORES     o que cada motor está fazendo — inclusive os desligados

Cada página é uma função sem argumento (é o que `st.Page` aceita); o período
escolhido na barra lateral chega por fechamento, montado uma vez em `_pagina`.
"""
from datetime import date

import streamlit as st

from components.auth import exigir_senha
from components.periodo import seletor_periodo
from components.theme import aplicar_tema, cabecalho

st.set_page_config(
    page_title="Recuperação · painel de operação",
    page_icon="◧",
    layout="wide",
)

exigir_senha()
aplicar_tema()

start_date, end_date = seletor_periodo()

if start_date > end_date:
    st.sidebar.error("A data inicial não pode ser maior que a final.")
    st.stop()

cabecalho(start_date, end_date)


def _pagina(builder, renderer, carregando: str, periodo: bool = True, antes=None):
    """Monta a função de página: carrega, renderiza, e contém o erro na página.

    Antes isso era um bloco de seis linhas repetido oito vezes no fim do arquivo;
    um erro em qualquer aba derrubava o render, mas o texto do `except` tinha que
    ser reescrito toda vez. Aqui o contrato é um só.
    """
    def render():
        if antes is not None:
            antes()
        with st.spinner(carregando):
            try:
                dados = builder(start_date, end_date) if periodo else builder()
                renderer(dados)
            except Exception as exc:
                st.error(f"Não consegui carregar esta página: {exc}")
                with st.expander("Detalhes do erro"):
                    st.exception(exc)
    return render


def _desligado(titulo: str, desde: str, motivo: str, religar: str):
    """Aviso de peça desligada, pra a página não virar tabela vazia sem explicação."""
    def aviso():
        # "está fora do ar" em vez de "desligado/desligada": o helper serve pra
        # peças de gênero diferente e não vale pedir a flexão a cada chamada.
        st.warning(
            f"**{titulo} está fora do ar desde {desde}.** {motivo}\n\n"
            f"Pra religar: {religar}"
        )
        st.caption(
            "Os dados abaixo são o histórico do que rodou — não vão avançar "
            "enquanto a automação estiver parada."
        )
    return aviso


# ── Operação ─────────────────────────────────────────────────────────────────
def _pulso():
    from processors.pulso import build_pulso
    from components.pulso_tab import render_pulso_tab
    return _pagina(build_pulso, render_pulso_tab, "Lendo o estado da operação...",
                   periodo=False)()


# ── Resultado ────────────────────────────────────────────────────────────────
def _recuperacoes():
    from processors.recovery import build_recovery_dataframe
    from components.recovery_tab import render_recovery_tab
    return _pagina(build_recovery_dataframe, render_recovery_tab,
                   "Carregando recuperações...")()


def _upsell():
    from processors.upsell import build_upsell_dataframe
    from components.upsell_tab import render_upsell_tab
    return _pagina(build_upsell_dataframe, render_upsell_tab, "Carregando upsell...")()


# ── ManyChat ─────────────────────────────────────────────────────────────────
def _efetividade():
    from processors.manychat_engagement import build_manychat_engagement
    from components.manychat_tab import render_manychat_tab
    return _pagina(build_manychat_engagement, render_manychat_tab,
                   "Carregando efetividade...")()


def _funil_etapas():
    from processors.manychat_funil import build_funis
    from components.manychat_funil_tab import render_funil_tab
    return _pagina(build_funis, render_funil_tab, "Carregando funil de etapas...")()


def _funil_venda():
    from processors.venda_funil import build_venda_funil
    from components.venda_funil_tab import render_venda_funil_tab
    return _pagina(build_venda_funil, render_venda_funil_tab,
                   "Carregando funil de venda...")()


# ── Motores ──────────────────────────────────────────────────────────────────
def _motor_recuperacao():
    from processors.recuperacao_migracao import build_recuperacao_migracao
    from components.recuperacao_migracao_tab import render_recuperacao_migracao_tab
    return _pagina(build_recuperacao_migracao, render_recuperacao_migracao_tab,
                   "Carregando motor de recuperação...")()


def _convite_aula():
    from processors.aula_convites import build_aula_convites
    from components.aula_tab import render_aula_tab
    return _pagina(
        build_aula_convites, render_aula_tab, "Carregando convites da aula...",
        antes=_desligado(
            "O convite da aula",
            "22/08/2026",
            "A grade do pg_cron continua batendo na hora certa, mas "
            "`convites_aula_config.ativo` está `false` — a edge function não manda "
            "nada, e a tabela `convites_aula` está zerada. A lista horária que "
            "alimentava o Make (`aula-dispatch.yml`) também foi desligada: a coluna "
            "`aula_chamada_em` nunca teve uma linha preenchida.",
            "vire `ativo` pra `true` em `convites_aula_config` depois de conferir "
            "`MC_TOKEN` e o `flow_ns` de cada etapa.",
        ),
    )()


def _grupo():
    from processors.group_followup import build_group_followup_dataframe
    from components.group_followup_tab import render_group_followup_tab

    _desligado(
        "A 2ª chamada pro grupo",
        "22/08/2026",
        "A tarefa do Windows que marcava a elegibilidade foi desabilitada porque o "
        "cenário do Make parou de consumir: `segunda_chamada_em` travou em 05/06 "
        "com 32.290 pessoas paradas como elegíveis. A lista abaixo continua "
        "valendo como consulta manual de quem comprou e não entrou no grupo.",
        "reative o cenário no Make e rode "
        "`Enable-ScheduledTask -TaskName RecoveryDashboard-GroupFollowup`.",
    )()

    hoje = date.today()
    cutoff = st.date_input(
        "Considerar compras a partir de",
        value=date(2026, 5, 10),
        max_value=hoje,
        format="DD/MM/YYYY",
        key="grupo_cutoff",
    )
    with st.spinner("Carregando pendentes de 2ª chamada..."):
        try:
            render_group_followup_tab(build_group_followup_dataframe(hoje, cutoff), cutoff)
        except Exception as exc:
            st.error(f"Não consegui carregar esta página: {exc}")
            with st.expander("Detalhes do erro"):
                st.exception(exc)


st.navigation({
    "Operação": [
        # Sem `url_path`: a página padrão mora na raiz, e declarar um caminho
        # pra ela faz o Streamlit responder "Page not found" no link direto.
        st.Page(_pulso, title="Pulso", default=True),
    ],
    "Resultado": [
        st.Page(_recuperacoes, title="Recuperações", url_path="recuperacoes"),
        st.Page(_upsell, title="Upsell", url_path="upsell"),
    ],
    "ManyChat": [
        st.Page(_efetividade, title="Efetividade", url_path="efetividade"),
        st.Page(_funil_etapas, title="Funil de etapas", url_path="funil-etapas"),
        st.Page(_funil_venda, title="Funil de venda", url_path="funil-venda"),
    ],
    "Motores": [
        st.Page(_motor_recuperacao, title="Recuperação", url_path="motor-recuperacao"),
        st.Page(_convite_aula, title="Convite da aula", url_path="convite-aula"),
        st.Page(_grupo, title="Grupo", url_path="grupo"),
    ],
}).run()
