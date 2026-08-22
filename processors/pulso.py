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


def build_pulso() -> dict:
    """Snapshot da operação. Não recebe período: 'o que está rodando' é agora."""
    fontes = _fontes()
    motores = _motores()

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

    crons = _crons()
    if not crons.empty:
        quebrados = crons[(crons["active"]) & (crons["falhas_24h"] > 0)]
        for _, c in quebrados.iterrows():
            alertas.append(
                f"Cron **{c['jobname']}** falhou {int(c['falhas_24h'])}× nas últimas 24h."
            )

    return {
        "fontes": fontes,
        "motores": motores,
        "crons": crons,
        "disparos": _disparos_recentes(),
        "mix_eventos": _mix_eventos(),
        "externas": EXTERNAS,
        "alertas": alertas,
        "lido_em": datetime.now(),
    }


def _humano(horas: float | None) -> str:
    if horas is None:
        return "—"
    if horas < 1:
        return f"{int(horas * 60)} min"
    if horas < 48:
        return f"{horas:.0f}h"
    return f"{horas / 24:.0f} dias"
