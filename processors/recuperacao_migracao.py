"""
processors/recuperacao_migracao.py
================================================================================
Motor próprio de recuperação (PIX / boleto expirado / carrinho) — a migração do
Make, lida pro dashboard.

Fonte: tabelas do 0008 no Postgres/Supabase.
  recuperacao_config   -> modo por tipo (off | simulado | teste | ligado) + trava `desde`
  recuperacao_etapas   -> a escada de cada tipo (atraso, template, fluxo, copy)
  recuperacao_disparos -> a fila: 1 linha por (evento, etapa)

Enquanto o modo for `simulado`, nada é mandado: o disparo é registrado com o
texto que TERIA sido enviado (coluna `preview`). É isso que permite rodar em
paralelo com o Make e comparar antes de virar a chave.

Status possíveis de um disparo:
  agendado  ainda não venceu
  simulado  venceu e foi registrado sem enviar (modo simulado / fora da whitelist)
  enviado   foi pro ManyChat de verdade
  cancelado saiu da fila (hoje só por 'ja comprou' — a supressão)
  erro      tentou e falhou (volta até 4 tentativas)
"""
import pandas as pd
from datetime import date

from clients.postgres import _read

STATUS_ORDEM = ["agendado", "simulado", "enviado", "cancelado", "erro"]


def build_recuperacao_migracao(start_date: date, end_date: date) -> dict:
    ini, fim = start_date.isoformat(), end_date.isoformat()

    config = _read("""
        select tipo, modo, origem, produto_like, desde, max_por_dia
        from recuperacao_config order by origem, tipo
    """)
    etapas = _read("""
        select tipo, etapa, ordem, atraso::text as atraso, template, flow_ns,
               texto_p1, texto_p2, ativo
        from recuperacao_etapas order by tipo, ordem
    """)
    testes = _read("select telefone_core, nome from recuperacao_teste_telefones order by criado_em")

    # Duas origens desde o 0009: PIX/boleto/carrinho nascem de recovery_events,
    # boas-vindas nasce de compras. O disparo aponta pra uma das duas.
    disparos = _read(f"""
        select d.id, d.tipo, d.etapa, d.status, coalesce(d.motivo, '') as motivo,
               d.quando_enviar, d.enviado_em, d.tentativas, coalesce(d.erro, '') as erro,
               coalesce(d.preview, '') as preview, d.telefone_core,
               coalesce(ev.nome, c.nome)   as nome,
               coalesce(ev.valor, c.valor) as valor,
               coalesce(ev.evento_em, c.compra_em) as evento_em
        from recuperacao_disparos d
        left join recovery_events ev on ev.id = d.evento_id
        left join compras         c  on c.id  = d.compra_id
        where (coalesce(ev.evento_em, c.compra_em) at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
    """)

    if not disparos.empty:
        for c in ("quando_enviar", "enviado_em", "evento_em"):
            disparos[c] = (
                pd.to_datetime(disparos[c], utc=True, errors="coerce")
                .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
            )
        disparos["valor"] = pd.to_numeric(disparos["valor"], errors="coerce").fillna(0.0)
        disparos["nome"] = disparos["nome"].fillna("")

    # ── Quadro por tipo × status ─────────────────────────────────────────────
    if disparos.empty:
        quadro = pd.DataFrame(columns=["tipo"] + STATUS_ORDEM)
    else:
        quadro = (
            disparos.pivot_table(index="tipo", columns="status", values="id",
                                 aggfunc="count", fill_value=0)
            .reindex(columns=STATUS_ORDEM, fill_value=0)
            .reset_index()
        )

    total = int(len(disparos))
    por_status = (
        disparos["status"].value_counts().to_dict() if not disparos.empty else {}
    )

    # Só conta como "coberto" o que o motor de fato resolveria: mandou ou
    # mandaria (simulado), fora o que a supressão tirou.
    resolvidos = int(por_status.get("enviado", 0)) + int(por_status.get("simulado", 0))
    cancelados = int(por_status.get("cancelado", 0))

    resumo = {
        "total": total,
        "agendados": int(por_status.get("agendado", 0)),
        "simulados": int(por_status.get("simulado", 0)),
        "enviados": int(por_status.get("enviado", 0)),
        "cancelados": cancelados,
        "erros": int(por_status.get("erro", 0)),
        "resolvidos": resolvidos,
        "taxa_supressao": (cancelados / total * 100) if total else 0.0,
        "modos": dict(zip(config["tipo"], config["modo"])) if not config.empty else {},
        "sem_fluxo": [
            f"{r['tipo']}/{r['etapa']}"
            for _, r in etapas.iterrows()
            if r["ativo"] and not r["flow_ns"]
        ] if not etapas.empty else [],
    }

    return {"config": config, "etapas": etapas, "testes": testes,
            "disparos": disparos, "quadro": quadro, "resumo": resumo}
