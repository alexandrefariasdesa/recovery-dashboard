"""
app.py — entrada do painel de operação.

Navegação em páginas (`st.navigation`), não abas. A diferença não é estética:
`st.tabs` renderiza o conteúdo de TODAS as abas em cada interação, então o
painel rodava as oito consultas pra mostrar uma. Com páginas, só a que está
aberta consulta o banco.

O menu espelha o NEGÓCIO, não a tecnologia. Ele já foi agrupado por sistema
(ManyChat, Motores) e isso partia o mesmo funil em duas seções: a boas-vindas
aparecia em "Motores", o clique dela em "ManyChat", e ninguém conseguia ler o
funil inteiro numa tela. Agora:

    VISÃO GERAL  como foi o período, funil a funil, com o dinheiro na frente
    FUNIS        um funil por página: resultado e detalhe no mesmo lugar
    OPERAÇÃO     as peças estão de pé? o que cada motor está fazendo?

A Visão Geral é a porta de entrada e leva pro detalhe; as páginas de OPERAÇÃO
respondem "está quebrado?", que é outra pergunta e por isso outra seção.

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


# ── Visão geral ──────────────────────────────────────────────────────────────
def _visao_geral():
    from processors.visao_geral import build_visao_geral
    from components.visao_geral_tab import render_visao_geral_tab
    return _pagina(build_visao_geral, render_visao_geral_tab,
                   "Lendo o resultado de cada funil...")()


# ── Funis ────────────────────────────────────────────────────────────────────
def _aquisicao():
    from processors.funis import build_aquisicao
    from components.funis_tab import render_aquisicao
    return _pagina(build_aquisicao, render_aquisicao, "Carregando aquisição...")()


def _boas_vindas():
    from processors.funis import build_boas_vindas
    from components.funis_tab import render_boas_vindas
    return _pagina(build_boas_vindas, render_boas_vindas, "Carregando boas-vindas...")()


def _boas_vindas_ig():
    from processors.boas_vindas_ig import build_boas_vindas_ig
    from components.boas_vindas_ig_tab import render_boas_vindas_ig
    return _pagina(build_boas_vindas_ig, render_boas_vindas_ig,
                   "Carregando boas-vindas do Instagram...")()


def _grupo_funil():
    from processors.funis import build_grupo
    from components.funis_tab import render_grupo
    return _pagina(build_grupo, render_grupo, "Carregando entradas no grupo...")()


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


def _aula_eventos():
    from processors.aula_eventos import build_aula_eventos
    from components.aula_eventos_tab import render_aula_eventos_tab
    return _pagina(build_aula_eventos, render_aula_eventos_tab,
                   "Lendo os eventos do webinário...")()


def _segunda_chamada():
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
    "Visão geral": [
        # Sem `url_path`: a página padrão mora na raiz, e declarar um caminho
        # pra ela faz o Streamlit responder "Page not found" no link direto.
        st.Page(_visao_geral, title="Visão geral", default=True),
    ],
    # Um funil por página, na ordem em que a cliente passa por eles: compra,
    # é recuperada se não pagou, recebe as boas-vindas, entra no grupo, leva
    # upsell, é convidada pra aula.
    "Funis": [
        st.Page(_aquisicao, title="Aquisição", url_path="aquisicao"),
        st.Page(_recuperacoes, title="Recuperação", url_path="recuperacao"),
        st.Page(_boas_vindas, title="Boas-vindas", url_path="boas-vindas"),
        st.Page(_boas_vindas_ig, title="Boas-vindas Instagram",
                url_path="boas-vindas-instagram"),
        st.Page(_grupo_funil, title="Grupo", url_path="grupo"),
        st.Page(_upsell, title="Upsell", url_path="upsell"),
        st.Page(_convite_aula, title="Aula", url_path="aula"),
        # A página acima é o que MANDAMOS; esta é o que aconteceu na sala.
        # Separadas porque uma depende do nosso motor e a outra da plataforma.
        st.Page(_aula_eventos, title="Webinário", url_path="webinario"),
    ],
    # "Está quebrado?" é outra pergunta que "quanto rendeu?" — por isso as peças
    # de diagnóstico ficam separadas dos funis, e não misturadas neles.
    "Operação": [
        st.Page(_pulso, title="Pulso", url_path="pulso"),
        st.Page(_motor_recuperacao, title="Motores", url_path="motores"),
        st.Page(_efetividade, title="Mensagens", url_path="efetividade"),
        st.Page(_funil_etapas, title="Etapas do fluxo", url_path="funil-etapas"),
        st.Page(_funil_venda, title="Disparo de venda", url_path="funil-venda"),
        st.Page(_segunda_chamada, title="2ª chamada (histórico)",
                url_path="segunda-chamada"),
    ],
}).run()
