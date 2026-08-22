"""
components/theme.py
================================================================================
Identidade visual do painel — "painel de operação".

A tese do sistema é hora cravada: o convite da aula sai 09h00 / 18h30 / 19h15 /
19h30, e a recuperação sai N minutos depois do evento. Então o horário é o
elemento visual central — números e horas em monoespaçada, com peso, e não
enfiados no meio de um texto.

E cada status tem UMA cor, que significa a mesma coisa em todas as abas:

    verde-pix   enviado / no ar          (o teal do PIX, artefato do domínio)
    âmbar       agendado / esperando a hora
    ardósia     cancelado pela supressão (não é erro: é o sistema acertando)
    vermelho    erro

Uso:
    from components.theme import aplicar_tema, cabecalho, STATUS_COR
    aplicar_tema()
    cabecalho(start_date, end_date)
"""
import streamlit as st

# ── Tokens ───────────────────────────────────────────────────────────────────
PAPEL      = "#F2F4F7"   # fundo: papel frio, não creme
SUPERFICIE = "#FFFFFF"
TINTA      = "#0F1720"   # quase preto, puxado pro azul
TINTA_2    = "#5B6879"
LINHA      = "#E1E6EC"

PIX        = "#00A98F"   # enviado / funcionando
AMBAR      = "#B87400"   # agendado / esperando
ARDOSIA    = "#64748B"   # cancelado (supressão)
VERMELHO   = "#C5303A"   # erro

STATUS_COR = {
    "enviado": PIX, "enviada": PIX, "no ar": PIX, "ligado": PIX,
    "agendado": AMBAR, "simulado": AMBAR, "teste": AMBAR,
    "cancelado": ARDOSIA, "off": ARDOSIA, "desligado": ARDOSIA,
    "erro": VERMELHO,
}

_FONTES = (
    "https://fonts.googleapis.com/css2"
    "?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800"
    "&family=Public+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500;600"
    "&display=swap"
)

_CSS = f"""
<style>
@import url('{_FONTES}');

:root {{
  --papel: {PAPEL}; --superficie: {SUPERFICIE};
  --tinta: {TINTA}; --tinta-2: {TINTA_2}; --linha: {LINHA};
  --pix: {PIX}; --ambar: {AMBAR}; --ardosia: {ARDOSIA}; --vermelho: {VERMELHO};
  --display: 'Bricolage Grotesque', system-ui, sans-serif;
  --corpo: 'Public Sans', system-ui, sans-serif;
  --mono: 'IBM Plex Mono', ui-monospace, monospace;
}}

[data-testid="stAppViewContainer"] {{ background: var(--papel); }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2.2rem; max-width: 1500px; }}

html, body, [data-testid="stAppViewContainer"] * {{
  font-family: var(--corpo);
  color: var(--tinta);
}}

h1, h2, h3 {{
  font-family: var(--display) !important;
  letter-spacing: -0.02em;
  color: var(--tinta) !important;
}}
h2 {{ font-size: 1.35rem !important; font-weight: 600 !important; margin-top: .4rem !important; }}
h3 {{ font-size: 1.05rem !important; font-weight: 600 !important; }}

/* ── Cabeçalho ─────────────────────────────────────────────────────────── */
.op-topo {{
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 1.5rem; flex-wrap: wrap;
  border-bottom: 2px solid var(--tinta); padding-bottom: .7rem; margin-bottom: .2rem;
}}
.op-marca {{
  font-family: var(--display); font-weight: 800; font-size: 2.1rem;
  letter-spacing: -0.035em; line-height: 1;
}}
.op-marca em {{ font-style: normal; color: var(--pix); }}
.op-sub {{
  font-family: var(--mono); font-size: .72rem; letter-spacing: .09em;
  text-transform: uppercase; color: var(--tinta-2); margin-top: .45rem;
}}

/* Faixa de status dos motores — a assinatura do painel */
.op-motores {{ display: flex; gap: .5rem; flex-wrap: wrap; }}
.op-motor {{
  background: var(--superficie); border: 1px solid var(--linha);
  border-left: 3px solid var(--ardosia);
  padding: .5rem .8rem; min-width: 190px;
}}
.op-motor[data-estado="ok"]      {{ border-left-color: var(--pix); }}
.op-motor[data-estado="espera"]  {{ border-left-color: var(--ambar); }}
.op-motor-nome {{
  font-family: var(--mono); font-size: .65rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--tinta-2);
}}
.op-motor-valor {{
  font-family: var(--mono); font-size: .95rem; font-weight: 600;
  margin-top: .15rem; font-variant-numeric: tabular-nums;
}}
.op-grade {{
  font-family: var(--mono); font-size: .9rem; font-weight: 600;
  letter-spacing: .02em; font-variant-numeric: tabular-nums; margin-top: .15rem;
}}
.op-grade span {{ color: var(--tinta-2); font-weight: 400; }}

/* ── Pulso: uma peça por cartão ────────────────────────────────────────── */
/* A régua da esquerda carrega o veredito, então o cartão pode ficar sóbrio:
   quem varre a página lê a coluna de cor antes de ler qualquer número. */
.op-pulso {{
  display: grid; gap: .6rem; margin: .4rem 0 .2rem;
  grid-template-columns: repeat(auto-fit, minmax(268px, 1fr));
}}
.op-peca {{
  background: var(--superficie); border: 1px solid var(--linha);
  border-left: 3px solid var(--ardosia); padding: .7rem .9rem .8rem;
}}
.op-peca[data-estado="ok"]      {{ border-left-color: var(--pix); }}
.op-peca[data-estado="atraso"]  {{ border-left-color: var(--ambar); }}
.op-peca[data-estado="erro"]    {{ border-left-color: var(--vermelho); }}
.op-peca[data-estado="mudo"]    {{ border-left-color: var(--ardosia); }}
.op-peca-topo {{
  display: flex; align-items: baseline; justify-content: space-between; gap: .5rem;
}}
.op-peca-nome {{
  font-family: var(--mono); font-size: .65rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--tinta-2);
}}
.op-peca-tag {{
  font-family: var(--mono); font-size: .6rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--tinta-2); white-space: nowrap;
}}
.op-peca[data-estado="ok"]     .op-peca-tag {{ color: var(--pix); }}
.op-peca[data-estado="atraso"] .op-peca-tag {{ color: var(--ambar); }}
.op-peca[data-estado="erro"]   .op-peca-tag {{ color: var(--vermelho); }}
.op-peca-valor {{
  font-family: var(--mono); font-size: 1.5rem; font-weight: 600;
  letter-spacing: -0.03em; font-variant-numeric: tabular-nums;
  margin: .2rem 0 .35rem; line-height: 1.1;
}}
.op-peca-linha {{
  font-size: .8rem; color: var(--tinta-2); line-height: 1.5;
}}
.op-peca-linha b {{ color: var(--tinta); font-weight: 600; font-family: var(--mono); }}
.op-peca-quem {{ font-size: .74rem; opacity: .85; }}

/* ── Navegação lateral: lista, não menu ────────────────────────────────── */
[data-testid="stSidebarNav"] ul {{ gap: 0; }}
[data-testid="stSidebarNav"] a span {{
  font-family: var(--mono); font-size: .72rem; letter-spacing: .05em;
}}
[data-testid="stSidebarNav"] div[class*="separator"], 
section[data-testid="stSidebar"] h2 {{
  font-family: var(--mono) !important; font-size: .62rem !important;
  letter-spacing: .14em; text-transform: uppercase; color: var(--tinta-2) !important;
}}
section[data-testid="stSidebar"] {{
  background: var(--superficie); border-right: 1px solid var(--linha);
}}

/* ── Métricas viram cartões ────────────────────────────────────────────── */
[data-testid="stMetric"] {{
  background: var(--superficie); border: 1px solid var(--linha);
  border-top: 2px solid var(--tinta); padding: .85rem 1rem .9rem;
}}
/* Rótulo pode quebrar em duas linhas — cortar o nome da métrica é pior que
   ocupar mais uma linha. */
[data-testid="stMetricLabel"] {{ white-space: normal !important; overflow: visible !important; }}
[data-testid="stMetricLabel"] p {{
  font-family: var(--mono) !important; font-size: .63rem !important;
  letter-spacing: .06em; text-transform: uppercase; line-height: 1.35;
  white-space: normal !important; color: var(--tinta-2) !important;
}}
/* Valor em duas linhas é melhor que "R$ 22…": valor cortado não informa nada. */
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{
  font-family: var(--mono) !important; font-weight: 600 !important;
  font-size: 1.35rem !important; font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em; line-height: 1.2;
  white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; overflow-wrap: anywhere;
}}

/* ── Abas: régua, não botões ───────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
  gap: 0; border-bottom: 1px solid var(--linha); margin-bottom: .4rem;
}}
.stTabs [data-baseweb="tab"] {{
  font-family: var(--mono); font-size: .72rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--tinta-2);
  padding: .55rem .9rem; border-radius: 0;
}}
.stTabs [aria-selected="true"] {{
  color: var(--tinta) !important; background: var(--superficie);
  box-shadow: inset 0 -2px 0 var(--pix);
}}
.stTabs [data-baseweb="tab-highlight"] {{ background: transparent !important; }}

/* ── Superfícies ───────────────────────────────────────────────────────── */
[data-testid="stExpander"] details {{
  background: var(--superficie); border: 1px solid var(--linha); border-radius: 0;
}}
[data-testid="stDataFrame"] {{ border: 1px solid var(--linha); }}
[data-testid="stDataFrame"] * {{ font-size: .82rem; }}
[data-testid="stCaptionContainer"] p {{ color: var(--tinta-2); font-size: .82rem; }}

/* Alertas: régua lateral em vez de caixa colorida — o aviso informa sem
   dominar a tela. A cor da régua segue o mesmo código de status do painel. */
[data-testid="stAlert"] {{
  border-radius: 0; background: var(--superficie) !important;
  border: 1px solid var(--linha); border-left: 3px solid var(--ardosia);
  padding: .7rem .9rem;
}}
[data-testid="stAlert"] p {{ font-size: .87rem; }}
[data-testid="stAlertContentWarning"] {{ border-left-color: var(--ambar); }}
[data-testid="stAlertContentError"] {{ border-left-color: var(--vermelho); }}
[data-testid="stAlertContentSuccess"] {{ border-left-color: var(--pix); }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{ border-left-color: var(--ambar); }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{ border-left-color: var(--vermelho); }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{ border-left-color: var(--pix); }}

/* Controles */
.op-espaco-rotulo {{ height: 1.85rem; }}   /* alinha o botão com os campos de data */
.stButton button {{
  border-radius: 0; border: 1px solid var(--tinta); background: var(--tinta);
  color: var(--papel); font-family: var(--mono); font-size: .72rem;
  letter-spacing: .06em; text-transform: uppercase; white-space: nowrap;
  height: 2.5rem; min-height: 2.5rem; padding: 0 .7rem;
}}
/* A regra global de cor lá em cima pega todo elemento; o botão precisa vencer
   ela explicitamente, senão o rótulo some no fundo escuro. */
.stButton button, .stButton button p {{ color: var(--papel) !important; }}
.stButton button:hover, .stButton button:hover p {{
  background: var(--pix); border-color: var(--pix); color: #fff !important;
}}
.stButton button p {{ font-size: .72rem !important; margin: 0; }}
[data-testid="stDateInput"] input, [data-testid="stSelectbox"] div {{ border-radius: 0; }}
label p {{ font-size: .78rem !important; color: var(--tinta-2) !important; }}

@media (prefers-reduced-motion: reduce) {{
  * {{ animation: none !important; transition: none !important; }}
}}
</style>
"""


def _registrar_template_plotly() -> None:
    """Template padrão do plotly, pra TODO gráfico do painel (inclusive os das
    abas antigas) sair na mesma paleta e na mesma tipografia, sem precisar
    tocar em cada um."""
    import plotly.graph_objects as go
    import plotly.io as pio

    if "op" in pio.templates:
        return
    pio.templates["op"] = go.layout.Template(layout=dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=[PIX, AMBAR, ARDOSIA, VERMELHO, TINTA_2],
        font=dict(family="'IBM Plex Mono', monospace", size=12, color=TINTA),
        title=dict(font=dict(family="'Bricolage Grotesque', sans-serif", size=15)),
        hoverlabel=dict(
            font=dict(family="'IBM Plex Mono', monospace", size=12),
            bgcolor=SUPERFICIE, bordercolor=LINHA,
        ),
        xaxis=dict(gridcolor=LINHA, zerolinecolor=LINHA, linecolor=LINHA),
        yaxis=dict(gridcolor=LINHA, zerolinecolor=LINHA, linecolor=LINHA),
        legend=dict(font=dict(size=11)),
        margin=dict(l=8, r=8, t=28, b=8),
    ))
    pio.templates.default = "plotly_white+op"


def aplicar_tema() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _registrar_template_plotly()


def dinheiro(valor: float, centavos: bool = False) -> str:
    """Moeda em português: R$ 226.521 (ponto no milhar, vírgula no centavo).
    Nos números de topo os centavos só atrapalham a leitura — por isso saem
    por padrão."""
    casas = 2 if centavos else 0
    bruto = f"{float(valor or 0):,.{casas}f}"
    return "R$ " + bruto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def grafico(fig, altura: int = 320):
    """Põe um gráfico plotly na mesma tipografia e no mesmo fundo do painel.
    Números e rótulos de eixo em monoespaçada, igual ao resto dos dados."""
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="'IBM Plex Mono', monospace", size=12, color=TINTA),
        hoverlabel=dict(
            font=dict(family="'IBM Plex Mono', monospace", size=12),
            bgcolor=SUPERFICIE, bordercolor=LINHA,
        ),
        colorway=[PIX, AMBAR, ARDOSIA, VERMELHO],
        xaxis=dict(gridcolor=LINHA, zerolinecolor=LINHA),
        yaxis=dict(gridcolor=LINHA, zerolinecolor=LINHA),
    )
    return fig


def _motor(nome: str, valor: str, estado: str = "") -> str:
    attr = f' data-estado="{estado}"' if estado else ""
    return (
        f'<div class="op-motor"{attr}>'
        f'<div class="op-motor-nome">{nome}</div>'
        f'<div class="op-motor-valor">{valor}</div></div>'
    )


@st.cache_data(ttl=60, show_spinner=False)
def _estado_motores() -> list[tuple[str, str, str]]:
    """Estado dos dois motores, pro cabeçalho. Silencioso: se o banco não
    responder, o cabeçalho simplesmente não mostra a faixa."""
    from clients.postgres import _read

    fora = []
    try:
        grade = _read("select to_char(hora_brt, 'HH24:MI') as h from convites_aula_etapas "
                      "where ativo and flow_ns is not null order by ordem")
        ligado = _read("select ativo from convites_aula_config limit 1")
        no_ar = bool(ligado.iloc[0]["ativo"]) if not ligado.empty else False
        horas = " ".join(grade["h"].tolist()) if not grade.empty else "sem grade"
        fora.append((
            "Convite da aula",
            horas if no_ar else f"{horas} · desligado",
            "ok" if no_ar else "espera",
        ))
    except Exception:
        pass

    try:
        cfg = _read("select modo, count(*) as n from recuperacao_config group by modo order by n desc")
        if not cfg.empty:
            modo = cfg.iloc[0]["modo"]
            rotulo = {"off": "desligado", "simulado": "simulado", "teste": "teste", "ligado": "no ar"}
            fora.append((
                "Recuperação",
                rotulo.get(modo, modo),
                "ok" if modo == "ligado" else ("espera" if modo in ("simulado", "teste") else ""),
            ))
    except Exception:
        pass

    return fora


def cabecalho(start_date, end_date) -> None:
    """Marca + faixa de status dos motores. A faixa é a assinatura do painel:
    mostra a grade de horários do dia, que é o que o sistema todo garante."""
    dias = (end_date - start_date).days + 1
    periodo = (
        f"{start_date.strftime('%d/%m')} — {end_date.strftime('%d/%m/%Y')} · {dias} "
        f"{'dia' if dias == 1 else 'dias'}"
    )

    motores = "".join(_motor(n, v, e) for n, v, e in _estado_motores())

    st.markdown(
        f"""
        <div class="op-topo">
          <div>
            <div class="op-marca">Recuperação<em>.</em></div>
            <div class="op-sub">{periodo}</div>
          </div>
          <div class="op-motores">{motores}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
