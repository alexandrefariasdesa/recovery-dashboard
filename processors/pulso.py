"""
processors/pulso.py
================================================================================
O que está rodando AGORA — a leitura de operação do painel.

As outras abas respondem "quanto o funil rendeu no período". Esta responde outra
pergunta, que não tinha dono: **as peças estão de pé?** Cada automação viva
deixa rastro numa tabela; se a tabela parou de crescer, a peça caiu — e é isso
que a página mostra, sem depender de período escolhido.

Três blocos:

  FONTES   tabelas que recebem escrita de fora (webhook, worker, sync). Pra cada
           uma: última linha, volume de 24h e 7d, e o veredito comparando o
           silêncio atual com `limite_h` (quanto tempo é normal ficar quieto).
  MOTORES  quem decide mandar mensagem: o motor de recuperação (modo por tipo)
           e o convite da aula (liga/desliga + grade de horários).
  CRONS    pg_cron do Supabase, com a última execução real de cada job — a
           verdade sobre o agendamento, não o que a gente lembra dele.

Fora do banco (tarefa do Windows, GitHub Actions) o painel não tem como olhar:
essas entram em EXTERNAS como registro declarado, com data e motivo, e ficam
marcadas como não-verificáveis em vez de fingir um status.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from clients.postgres import _read


# ── Fontes: quem escreve, onde, e quanto silêncio é normal ───────────────────
# `limite_h` é o que separa "quieto" de "caiu". Escolhido pelo ritmo observado
# de cada fonte, não por um número redondo: o clique é raro por natureza (dezenas
# por dia), o evento do ManyChat é constante (milhares por dia).
FONTES = [
    {
        "chave": "compras",
        "titulo": "Compras",
        "tabela": "compras",
        "coluna": "compra_em",
        "quem": "webhook Payt → edge function `payt-webhook`",
        "limite_h": 24,
    },
    {
        "chave": "recovery_events",
        "titulo": "Eventos de recuperação",
        "tabela": "recovery_events",
        "coluna": "evento_em",
        "quem": "webhook Payt (pix/boleto gerado, expirado, carrinho)",
        "limite_h": 12,
    },
    {
        "chave": "manychat_eventos",
        "titulo": "Eventos do ManyChat",
        "tabela": "manychat_eventos",
        "coluna": "evento_em",
        "quem": "worker `recovery-flow-tracker` (Cloudflare) → PostgREST",
        "limite_h": 6,
    },
    {
        "chave": "manychat_cliques",
        "titulo": "Cliques do ManyChat",
        "tabela": "manychat_cliques",
        "coluna": "clicado_em",
        "quem": "worker `manychat-click-tracker` → Sheets → sync do Actions (30 min)",
        "limite_h": 48,
    },
    {
        "chave": "recuperacao_disparos",
        "titulo": "Fila do motor de recuperação",
        "tabela": "recuperacao_disparos",
        "coluna": "criado_em",
        "quem": "pg_cron `recuperacao-agendar` monta, `recuperacao-disparar` drena",
        "limite_h": 24,
    },
]

# Automações que vivem fora do Postgres. O painel não consegue verificar estado
# aqui — então o campo é declarado, com a data em que mudou e como reverter.
EXTERNAS = [
    {
        "titulo": "Sync ManyChat (cliques)",
        "onde": "GitHub Actions · `manychat-sync.yml`",
        "estado": "no ar",
        "detalhe": "a cada 30 min, só a aba `cliques_manychat`",
        "desde": "22/08/2026",
        "nota": "os eventos saíram do sync: o worker grava direto no Postgres desde 12/08.",
    },
    {
        "titulo": "2ª chamada pro grupo",
        "onde": "Tarefa do Windows · `RecoveryDashboard-GroupFollowup`",
        "estado": "desligado",
        "detalhe": "era 08h e 20h, escrevia a elegibilidade na planilha Leads",
        "desde": "22/08/2026",
        "nota": "o Make parou de consumir: `segunda_chamada_em` travou em 05/06 com "
                "32.290 pessoas marcadas elegíveis. Religar só depois de reativar o cenário.",
    },
    {
        "titulo": "Disparo Aula (lista horária)",
        "onde": "GitHub Actions · `aula-dispatch.yml`",
        "estado": "desligado",
        "detalhe": "montava a aba `Disparo Aula` de hora em hora pro Make",
        "desde": "22/08/2026",
        "nota": "`aula_chamada_em` nunca teve uma linha preenchida — o Make jamais leu a aba.",
    },
]

# Do outro lado da migração está o Make (e, na boas-vindas, a automação de compra
# aprovada). O painel não tem acesso a nenhum dos dois — então isto é registro
# DECLARADO, no mesmo espírito de EXTERNAS: serve pra cruzar com o modo do motor
# e gritar a única combinação perigosa, "ligado aqui E ligado lá" (mensagem dupla).
MAKE_CENARIOS = {
    "pix_gerado": {
        "estado": "pausado",
        "onde": "Make · cenário PIX/boleto gerado",
        "desde": "21/08/2026",
    },
    "pix_expirado": {
        "estado": "ativo",
        "onde": "Make · cenário PIX/boleto expirado",
        "desde": "—",
    },
    "boleto_expirado": {
        "estado": "ativo",
        "onde": "Make · cenário PIX/boleto expirado (mesmo fluxo do pix_expirado)",
        "desde": "—",
    },
    "carrinho_abandonado": {
        "estado": "pausado",
        "onde": "Make · cenário de carrinho abandonado",
        "desde": "22/08/2026",
    },
    "compra_posicoes": {
        "estado": "ativo",
        "onde": "automação de compra aprovada → BOAS VINDAS PS",
        "desde": "—",
    },
    "compra_protocolo": {
        "estado": "ativo",
        "onde": "automação de compra aprovada → BOAS VINDAS PP",
        "desde": "—",
    },
}

# Onde o operador sabe mais que a estatística. O p99 dos intervalos é uma boa
# régua pra fonte que chega o dia todo, mas mente pra fonte em lote: a Payt varre
# os vencidos de tempos em tempos e passar um dia inteiro sem nenhum expirado é
# normal, não é queda. Aqui o número é declarado, com o porquê.
LIMITE_TIPO = {
    # "assim mesmo, não dispara toda hora" — confirmado pelo usuário em 22/08.
    "pix_expirado": {"limite_h": 24, "porque": "a Payt manda os vencidos em lote, não de hora em hora"},
}

# Tipos desligados de propósito. Não adianta alertar todo dia por uma fonte que
# ninguém espera de volta — ela aparece como desligada, não como quebrada.
TIPOS_DESATIVADOS = {
    "boleto_expirado": "boleto saiu como forma de pagamento (sem um evento desde 05/08/2026)",
}

_MODO_ORDEM = {"ligado": 0, "teste": 1, "simulado": 2, "off": 3}


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _horas_desde(ts) -> float | None:
    if ts is None or pd.isna(ts):
        return None
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return (_agora_utc() - ts.to_pydatetime()).total_seconds() / 3600.0


def _veredito(horas: float | None, limite_h: int) -> str:
    """ok = escreveu dentro do esperado · atraso = passou do limite · mudo = nunca escreveu."""
    if horas is None:
        return "mudo"
    if horas <= limite_h:
        return "ok"
    return "atraso"


@st.cache_data(ttl=60, show_spinner=False)
def _fontes() -> pd.DataFrame:
    linhas = []
    for f in FONTES:
        try:
            d = _read(
                "select count(*) as total, max({c}) as ultima, "
                "count(*) filter (where {c} >= now() - interval '24 hours') as d1, "
                "count(*) filter (where {c} >= now() - interval '7 days') as d7 "
                "from {t}".format(c=f["coluna"], t=f["tabela"])
            ).iloc[0]
            horas = _horas_desde(d["ultima"])
            linhas.append({
                **f,
                "total": int(d["total"]),
                "ultima": d["ultima"],
                "d1": int(d["d1"]),
                "d7": int(d["d7"]),
                "horas": horas,
                "estado": _veredito(horas, f["limite_h"]),
                "erro": None,
            })
        except Exception as exc:  # uma fonte quebrada não pode derrubar a página
            linhas.append({**f, "total": 0, "ultima": None, "d1": 0, "d7": 0,
                           "horas": None, "estado": "erro", "erro": str(exc)[:160]})
    return pd.DataFrame(linhas)


@st.cache_data(ttl=60, show_spinner=False)
def _motores() -> dict:
    fora: dict = {"recuperacao": pd.DataFrame(), "aula": {}, "erro": None}
    try:
        cfg = _read(
            "select tipo, modo, desde, max_por_dia from recuperacao_config order by tipo"
        )
        if not cfg.empty:
            cfg["ordem"] = cfg["modo"].map(_MODO_ORDEM).fillna(9)
            cfg = cfg.sort_values(["ordem", "tipo"]).drop(columns="ordem")
            # O estado do outro lado não vem do banco: é declarado em MAKE_CENARIOS.
            cfg["fora_estado"] = cfg["tipo"].map(
                lambda t: MAKE_CENARIOS.get(t, {}).get("estado", "desconhecido"))
            cfg["fora_onde"] = cfg["tipo"].map(
                lambda t: MAKE_CENARIOS.get(t, {}).get("onde", "—"))
            cfg["fora_desde"] = cfg["tipo"].map(
                lambda t: MAKE_CENARIOS.get(t, {}).get("desde", "—"))
        fora["recuperacao"] = cfg
    except Exception as exc:
        fora["erro"] = str(exc)[:160]

    try:
        cfg = _read("select ativo, max_por_dia, cutoff_compra from convites_aula_config limit 1")
        grade = _read(
            "select to_char(hora_brt, 'HH24:MI') as h, etapa, ativo, flow_ns "
            "from convites_aula_etapas order by ordem"
        )
        pend = _read("select count(*) as n from convites_aula")
        fora["aula"] = {
            "ativo": bool(cfg.iloc[0]["ativo"]) if not cfg.empty else False,
            "max_por_dia": int(cfg.iloc[0]["max_por_dia"]) if not cfg.empty else 0,
            "grade": grade,
            "convites": int(pend.iloc[0]["n"]) if not pend.empty else 0,
        }
    except Exception as exc:
        fora["erro"] = fora["erro"] or str(exc)[:160]
    return fora


@st.cache_data(ttl=60, show_spinner=False)
def _crons() -> pd.DataFrame:
    """pg_cron + a última execução real de cada job.

    `cron.job_run_details` é a parte que importa: um job pode estar `active` e
    mesmo assim falhar toda vez. Sem a última execução, a lista de crons é só
    uma lista de intenções.
    """
    try:
        return _read("""
            with ultima as (
                select distinct on (jobid) jobid, status, start_time, return_message
                from cron.job_run_details
                order by jobid, start_time desc
            ),
            falhas as (
                select jobid, count(*) as falhas_24h
                from cron.job_run_details
                where start_time >= now() - interval '24 hours' and status <> 'succeeded'
                group by jobid
            )
            select j.jobname, j.schedule, j.active,
                   u.status, u.start_time as ultima, u.return_message as msg,
                   coalesce(f.falhas_24h, 0) as falhas_24h
            from cron.job j
            left join ultima u on u.jobid = j.jobid
            left join falhas f on f.jobid = j.jobid
            order by j.jobname
        """)
    except Exception:
        # pg_cron pode não estar exposto pro usuário do pooler — a página segue
        # sem o bloco em vez de quebrar inteira.
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _disparos_recentes() -> pd.DataFrame:
    try:
        return _read("""
            select tipo, etapa, status, count(*) as n, max(criado_em) as ultimo
            from recuperacao_disparos
            where criado_em >= now() - interval '24 hours'
            group by 1, 2, 3
            order by n desc
        """)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _mix_eventos() -> pd.DataFrame:
    """Volume por fluxo nos últimos 7 dias — é onde um worker em loop aparece."""
    try:
        return _read("""
            select fluxo, count(*) as n, max(evento_em) as ultimo,
                   count(distinct telefone_norm) as pessoas
            from manychat_eventos
            where evento_em >= now() - interval '7 days'
            group by 1
            order by n desc
        """)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def _eventos_por_tipo() -> pd.DataFrame:
    """Silêncio por TIPO de evento, não pela tabela.

    A tabela `recovery_events` recebe os quatro tipos, e o `pix_gerado` sozinho
    é ~150 linhas/dia — então ela nunca fica quieta, mesmo que um tipo inteiro
    tenha parado de chegar. O cartão da fonte, olhando só o `max(evento_em)`,
    mostra "de pé" enquanto uma origem morre.

    O limite de cada tipo não é chutado: é o **p99 dos intervalos observados nos
    últimos 30 dias**. Cada fonte tem o próprio ritmo (o carrinho chega o dia
    todo, o expirado é esparso), e comparar com o próprio histórico é a única
    régua que não precisa de manutenção. Piso de 2h pra não gritar com fonte
    rápida que respirou.
    """
    try:
        return _read("""
            with ev as (
                select tipo, evento_em,
                       lag(evento_em) over (partition by tipo order by evento_em) as ant
                from recovery_events
                where evento_em >= now() - interval '30 days'
            ),
            ritmo as (
                select tipo,
                       percentile_cont(0.99) within group (
                           order by extract(epoch from (evento_em - ant)) / 3600.0
                       ) as p99_h,
                       count(*) as intervalos
                from ev where ant is not null
                group by tipo
            )
            select e.tipo,
                   max(e.evento_em) as ultima,
                   count(*) filter (where e.evento_em >= now() - interval '24 hours') as d1,
                   count(*) filter (where e.evento_em >= now() - interval '7 days') as d7,
                   count(*) as d30,
                   r.p99_h, coalesce(r.intervalos, 0) as intervalos
            from recovery_events e
            left join ritmo r on r.tipo = e.tipo
            where e.evento_em >= now() - interval '30 days'
            group by e.tipo, r.p99_h, r.intervalos
            order by d7 desc, e.tipo
        """)
    except Exception:
        return pd.DataFrame()


def _classificar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Traduz silêncio + ritmo próprio em veredito, sem inventar número redondo."""
    if df.empty:
        return df
    df = df.copy()
    df["horas"] = df["ultima"].map(_horas_desde)

    def limite(r):
        # Declarado ganha do medido: quem opera a fonte sabe se o silêncio é ritmo.
        if r["tipo"] in LIMITE_TIPO:
            return float(LIMITE_TIPO[r["tipo"]]["limite_h"])
        # Menos de 30 intervalos em 30 dias é pouco pra ter ritmo — não dá pra
        # acusar atraso com essa base, então a fonte fica em observação.
        if pd.notna(r["p99_h"]) and r["intervalos"] >= 30:
            return max(float(r["p99_h"]), 2.0)
        return None

    df["limite_h"] = df.apply(limite, axis=1)
    df["limite_declarado"] = df["tipo"].map(
        lambda t: LIMITE_TIPO.get(t, {}).get("porque"))

    def estado(r):
        if r["tipo"] in TIPOS_DESATIVADOS:
            return "desativado"      # parou porque foi desligado, não porque caiu
        if r["d7"] == 0:
            return "parado"          # não chega há uma semana e ninguém avisou
        if r["limite_h"] is None:
            return "pouco dado"
        if r["horas"] is None:
            return "mudo"
        return "ok" if r["horas"] <= r["limite_h"] else "atraso"

    df["estado"] = df.apply(estado, axis=1)
    return df


def build_pulso() -> dict:
    """Snapshot da operação. Não recebe período: 'o que está rodando' é agora."""
    fontes = _fontes()
    motores = _motores()
    tipos = _classificar_tipos(_eventos_por_tipo())

    alertas = []
    for _, f in fontes.iterrows():
        if f["estado"] == "atraso":
            alertas.append(
                f"**{f['titulo']}** sem escrita há {_humano(f['horas'])} "
                f"(o normal é no máximo {f['limite_h']}h) — {f['quem']}."
            )
        elif f["estado"] == "erro":
            alertas.append(f"**{f['titulo']}**: a consulta falhou — `{f['erro']}`.")
        elif f["estado"] == "mudo":
            alertas.append(f"**{f['titulo']}** nunca recebeu uma linha.")

    # Um tipo pode morrer dentro de uma tabela que continua crescendo.
    for _, t in (tipos.iterrows() if not tipos.empty else []):
        if t["estado"] == "atraso":
            regua = (t["limite_declarado"] if t["limite_declarado"]
                     else "p99 dos intervalos de 30 dias")
            alertas.append(
                f"Evento **{t['tipo']}** sem chegar há {_humano(t['horas'])} — "
                f"o normal desta origem é no máximo {_humano(t['limite_h'])} "
                f"({regua}). A tabela segue recebendo os outros tipos."
            )
        elif t["estado"] == "parado":
            alertas.append(
                f"Evento **{t['tipo']}** não chega há mais de 7 dias "
                f"(último em {_quando_br(t['ultima'])}). Se foi de propósito, "
                "vale desativar o tipo no motor pra não ficar peça morta."
            )

    # A colisão que custa caro: o motor mandando de verdade num tipo em que a
    # automação de fora também continua mandando — a pessoa recebe duas vezes.
    cfg_rec = motores.get("recuperacao")
    if cfg_rec is not None and not cfg_rec.empty and "fora_estado" in cfg_rec.columns:
        for _, r in cfg_rec[(cfg_rec["modo"] == "ligado")
                            & (cfg_rec["fora_estado"] == "ativo")].iterrows():
            alertas.append(
                f"**{r['tipo']}** está `ligado` aqui e o registro diz que "
                f"{r['fora_onde']} continua ativo — risco de mensagem dupla. "
                "Pause lá ou volte este tipo pra `teste`."
            )

    crons = _crons()
    if not crons.empty:
        quebrados = crons[(crons["active"]) & (crons["falhas_24h"] > 0)]
        for _, c in quebrados.iterrows():
            alertas.append(
                f"Cron **{c['jobname']}** falhou {int(c['falhas_24h'])}× nas últimas 24h."
            )

    return {
        "fontes": fontes,
        "tipos": tipos,
        "motores": motores,
        "crons": crons,
        "disparos": _disparos_recentes(),
        "mix_eventos": _mix_eventos(),
        "externas": EXTERNAS,
        "alertas": alertas,
        "lido_em": datetime.now(),
    }


def _quando_br(ts) -> str:
    if ts is None or pd.isna(ts):
        return "nunca"
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/Sao_Paulo").tz_localize(None)
    return ts.strftime("%d/%m %H:%M")


def _humano(horas: float | None) -> str:
    if horas is None:
        return "—"
    if horas < 1:
        return f"{int(horas * 60)} min"
    if horas < 48:
        return f"{horas:.0f}h"
    return f"{horas / 24:.0f} dias"
