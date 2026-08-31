"""
processors/aula_convites.py
================================================================================
Convite pra AULA aos 7 dias de compra — leitura pro dashboard.

Fonte: Postgres/Supabase, tabelas do 0005/0006/0007:
  convites_aula        -> 1 linha por compradora convidada (nunca repete)
  convites_aula_envios -> 1 linha por (convidada, etapa, dia da aula)
  convites_aula_etapas -> catálogo das 4 etapas (hora, template, fluxo, copy)

A cadência do dia NÃO vive mais no ManyChat: cada uma das 4 mensagens é
disparada pelo pg_cron na hora cravada (09h00 / 18h30 / 19h15 / 19h30 BRT)
chamando a edge function `aula-convite`, que fala direto com a API do ManyChat.
Então o funil do dia é, literalmente, quantas linhas 'enviada' cada etapa tem.

Devolve um dicionário com:
  etapas   -> catálogo (etapa, ordem, hora, template, flow_ns, ativo, copy)
  funil    -> uma linha por etapa no período: enviadas, erros, % sobre convidadas
  por_dia  -> uma linha por dia da aula × etapa (pra série temporal)
  convites -> as convidadas do período (status, tentativas, erro)
  resumo   -> números de topo (convidadas, cobertura da última etapa, etc.)

DUPLA CHECAGEM: 'enviada' no nosso banco quer dizer "o ManyChat aceitou o
sendFlow" — e isso já mentiu. Em 30/08 o disparo respondeu 200, gravou os
campos e contou como enviada com o contato sem opt-in no canal: o WhatsApp
não entregou nada e nenhum sistema reclamou. Por isso o funil ganhou uma
segunda testemunha, independente do disparo: os tijolos de Solicitação
Externa dentro dos fluxos do ManyChat (`manychat_eventos`, gravados pelo
worker recovery-flow-tracker), no mesmo padrão dos funis da recuperação.

  etapa `recebeu` -> o fluxo REALMENTE rodou pra aquela pessoa
  etapa `entrou`  -> ela tocou no botão (só nas duas da noite, onde o botão
                     continua dentro do fluxo; nas duas primeiras é link e o
                     ManyChat não vê o clique)

Divergência entre as duas colunas é o alarme: banco alto e ManyChat baixo =
o disparo achou que mandou e o fluxo não rodou.
"""
import pandas as pd
from datetime import date

from clients.postgres import _read


def _q(sql: str) -> pd.DataFrame:
    return _read(sql)


def build_aula_convites(start_date: date, end_date: date) -> dict:
    ini, fim = start_date.isoformat(), end_date.isoformat()

    etapas = _q("""
        select etapa, ordem, hora_brt, template, flow_ns, ativo, texto_p1, texto_p2
        from convites_aula_etapas
        order by ordem
    """)

    # Convidadas do período (aula_data = o dia em que o convite saiu).
    convites = _q(f"""
        select id, nome, telefone, aula_data, status, tentativas, erro,
               mc_subscriber_id, link_sala, enviada_em, selecionada_em
        from convites_aula
        where coalesce(aula_data, (selecionada_em at time zone 'America/Sao_Paulo')::date)
              between '{ini}' and '{fim}'
    """)

    envios = _q(f"""
        select e.etapa, e.aula_data, e.status, e.tentativas, e.erro, e.enviada_em
        from convites_aula_envios e
        where e.aula_data between '{ini}' and '{fim}'
    """)

    # A 2ª testemunha: o próprio ManyChat avisando que o fluxo rodou/foi tocado.
    # O slug do fluxo é 'aula_' + o nome da etapa, então o join é direto.
    confirmacoes = _q(f"""
        select replace(fluxo, 'aula_', '') as etapa, etapa as marco,
               count(distinct coalesce(nullif(subscriber_id, ''), telefone)) as pessoas
        from manychat_eventos
        where left(fluxo, 5) = 'aula_'
          and (evento_em at time zone 'America/Sao_Paulo')::date between '{ini}' and '{fim}'
        group by 1, 2
    """)

    # Quem tocou BLOQUEAR nas mensagens da aula (a origem carimba o fluxo).
    bloqueios = _q(f"""
        select split_part(origem, 'aula_', 2) as etapa, acao,
               count(distinct telefone_core) as pessoas
        from optout_log
        where strpos(origem, 'aula_') > 0
          and (criado_em at time zone 'America/Sao_Paulo')::date between '{ini}' and '{fim}'
        group by 1, 2
    """)

    if not convites.empty:
        convites["aula_data"] = pd.to_datetime(convites["aula_data"], errors="coerce").dt.date
        convites["tentativas"] = pd.to_numeric(convites["tentativas"], errors="coerce").fillna(0).astype(int)
        for c in ("nome", "telefone", "status", "erro"):
            convites[c] = convites[c].fillna("").astype(str)

    if not envios.empty:
        envios["aula_data"] = pd.to_datetime(envios["aula_data"], errors="coerce").dt.date
        envios["erro"] = envios["erro"].fillna("").astype(str)

    convidadas = int(len(convites))

    # ── Funil: uma linha por etapa, na ordem da grade do dia ──────────────────
    def _confirma(etapa: str, marco: str) -> int:
        if confirmacoes.empty:
            return 0
        m = confirmacoes[(confirmacoes["etapa"] == etapa) & (confirmacoes["marco"] == marco)]
        return int(m["pessoas"].iloc[0]) if not m.empty else 0

    def _bloqueios(etapa: str) -> int:
        if bloqueios.empty:
            return 0
        m = bloqueios[(bloqueios["etapa"] == etapa) & (bloqueios["acao"] == "bloquear")]
        return int(m["pessoas"].iloc[0]) if not m.empty else 0

    # Só as duas etapas da noite têm botão que continua no fluxo; nas outras o
    # clique é num link e ninguém consegue vê-lo. Guardar isso aqui evita que a
    # tela mostre "0 cliques" onde o certo é "não dá pra medir".
    MEDE_CLIQUE = {"ao_vivo", "comecamos"}

    linhas = []
    for _, e in etapas.iterrows():
        se = envios[envios["etapa"] == e["etapa"]] if not envios.empty else pd.DataFrame()
        enviadas = int((se["status"] == "enviada").sum()) if not se.empty else 0
        erros = int((se["status"] == "erro").sum()) if not se.empty else 0
        confirmadas = _confirma(e["etapa"], "recebeu")
        linhas.append({
            "confirmadas": confirmadas,
            "confere": (confirmadas / enviadas * 100) if enviadas else 0.0,
            "cliques": _confirma(e["etapa"], "entrou"),
            "mede_clique": e["etapa"] in MEDE_CLIQUE,
            "bloqueios": _bloqueios(e["etapa"]),
            "etapa": e["etapa"],
            "ordem": int(e["ordem"]),
            "hora": str(e["hora_brt"])[:5],
            "template": e["template"] or "",
            "configurada": bool(e["flow_ns"]),
            "ativa": bool(e["ativo"]),
            "enviadas": enviadas,
            "erros": erros,
            "cobertura": (enviadas / convidadas * 100) if convidadas else 0.0,
        })
    funil = pd.DataFrame(linhas).sort_values("ordem").reset_index(drop=True)

    # ── Série por dia da aula × etapa ─────────────────────────────────────────
    if envios.empty:
        por_dia = pd.DataFrame(columns=["aula_data", "etapa", "enviadas", "erros"])
    else:
        por_dia = (
            envios.assign(
                enviadas=(envios["status"] == "enviada").astype(int),
                erros=(envios["status"] == "erro").astype(int),
            )
            .groupby(["aula_data", "etapa"], as_index=False)[["enviadas", "erros"]]
            .sum()
        )

    primeira = funil.iloc[0]["enviadas"] if not funil.empty else 0
    ultima = funil.iloc[-1]["enviadas"] if not funil.empty else 0

    resumo = {
        "convidadas": convidadas,
        "convites_ok": int((convites["status"] == "enviada").sum()) if not convites.empty else 0,
        "convites_erro": int((convites["status"] == "erro").sum()) if not convites.empty else 0,
        "primeira_etapa": int(primeira),
        "ultima_etapa": int(ultima),
        "retencao": (ultima / primeira * 100) if primeira else 0.0,
        "etapas_sem_fluxo": [r["etapa"] for _, r in funil.iterrows() if not r["configurada"]],
        "sem_rastreio": [r["etapa"] for _, r in funil.iterrows()
                         if r["enviadas"] and not r["confirmadas"]],
        "bloqueios": int(funil["bloqueios"].sum()) if not funil.empty else 0,
    }

    return {"etapas": etapas, "funil": funil, "por_dia": por_dia,
            "convites": convites, "envios": envios, "resumo": resumo,
            "confirmacoes": confirmacoes, "bloqueios": bloqueios}
