"""
processors/boas_vindas_ig.py
================================================================================
Funil do fluxo de BOAS-VINDAS DO INSTAGRAM (automação "boas vindas posições 2",
no ar desde 17/07/2026):

    recebeu  →  entrou  →  engajou

Fonte: `manychat_eventos` (slug `fluxo='boas_vindas'`), gravada pelos tijolos de
External Request do próprio fluxo via Worker `recovery-flow-tracker`.

Por que uma página só pra esse fluxo, se "Etapas do fluxo" já lista todos:
lá o fluxo é uma linha numa tabela com os outros quatro. Aqui cabe o ritmo
diário, a taxa etapa a etapa e — principalmente — a resposta sobre COMPRA.

**Sobre a compra: a chave é o UTM, não a pessoa.** O fluxo é do Instagram e não
captura telefone. Os eventos
chegam com `subscriber_id` do Instagram e `telefone` vazio; `compras` identifica
a pessoa por telefone/e-mail. Não existe hoje chave que ligue os dois lados — na
varredura de 30/08/2026, de 93.606 pessoas do fluxo apenas 1 tinha telefone em
qualquer evento, e a interseção com `manychat_cliques` (onde mora o clique que
vira venda) era zero.

A saída é atribuir pela ORIGEM em vez da pessoa: a Payt manda os parâmetros de
UTM do link no webhook, e desde a migration 0020 eles ficam em `compras.utm`.
Uma venda com o UTM do fluxo é uma venda do fluxo, sem precisar saber quem é.
Como o UTM só passa a ser gravado a partir do deploy do webhook, a página mostra
a distribuição real dos valores observados e deixa você marcar quais pertencem a
este fluxo — em vez de embutir um palpite de slug no código.

A ponte por telefone continua calculada como segunda via: ela acende sozinha se
algum dia o fluxo passar a pedir contato.
"""
import pandas as pd
import streamlit as st

from clients.postgres import _read

# Slug do fluxo do Instagram dentro de `manychat_eventos`.
FLUXO = "boas_vindas"

# A etiqueta de origem que o link deste fluxo carrega até o checkout da Payt.
# Casamos contra o conteúdo INTEIRO do `utm` (jsonb como texto) em vez de fixar
# um campo: a mesma etiqueta pode chegar como utm_campaign num link e utm_content
# noutro, e o que importa é ela estar lá.
UTM_FLUXO = "v4-manychat-dm"

ETAPAS = ["recebeu", "entrou", "engajou"]
ETAPA_LABEL = {"recebeu": "Recebeu", "entrou": "Entrou", "engajou": "Engajou"}

# Os outros fluxos de boas-vindas que existem na base (WhatsApp), mostrados como
# contexto no rodapé da página — não fazem parte do funil do Instagram.
OUTROS_SLUGS = {
    "boas_vindas_ps": "Boas-vindas PS (WhatsApp)",
    "boas_vindas_pp": "Boas-vindas PP (WhatsApp)",
}


def _sp(s):
    """timestamptz (UTC) → parede de relógio de São Paulo, sem fuso."""
    return (pd.to_datetime(s, utc=True, errors="coerce")
              .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None))


@st.cache_data(ttl=120, show_spinner=False)
def build_boas_vindas_ig(start_date, end_date) -> dict:
    """Funil do fluxo de boas-vindas do Instagram no período.

    Pessoas distintas por etapa: `subscriber_id` quando existe, senão o telefone
    normalizado — mesma chave das outras páginas de funil, pra quem clica duas
    vezes não contar duas.
    """
    per = {"ini": start_date, "fim": end_date, "fluxo": FLUXO}

    # ── Funil: pessoas distintas por etapa ──────────────────────────────────
    resumo_raw = _read("""
        select etapa, count(distinct pkey) as pessoas
        from (
          select etapa,
                 coalesce(nullif(subscriber_id, ''), nullif(telefone_norm, '')) as pkey
          from public.manychat_eventos
          where fluxo = '{fluxo}'
            and etapa in ('recebeu', 'entrou', 'engajou')
            and (evento_em at time zone 'America/Sao_Paulo')::date
                between '{ini}' and '{fim}'
        ) t
        where pkey is not null
        group by etapa
    """.format(**per))

    pessoas = {r["etapa"]: int(r["pessoas"]) for _, r in resumo_raw.iterrows()} \
        if not resumo_raw.empty else {}
    recebeu = pessoas.get("recebeu", 0)
    entrou = pessoas.get("entrou", 0)
    engajou = pessoas.get("engajou", 0)

    funil = pd.DataFrame([
        {"etapa": e, "Etapa": ETAPA_LABEL[e], "Pessoas": pessoas.get(e, 0)}
        for e in ETAPAS
    ])

    # ── Ritmo diário ────────────────────────────────────────────────────────
    diario = _read("""
        select dia, etapa, count(distinct pkey) as pessoas
        from (
          select (evento_em at time zone 'America/Sao_Paulo')::date as dia,
                 etapa,
                 coalesce(nullif(subscriber_id, ''), nullif(telefone_norm, '')) as pkey
          from public.manychat_eventos
          where fluxo = '{fluxo}'
            and etapa in ('recebeu', 'entrou', 'engajou')
            and (evento_em at time zone 'America/Sao_Paulo')::date
                between '{ini}' and '{fim}'
        ) t
        where pkey is not null
        group by dia, etapa
        order by dia
    """.format(**per))
    if not diario.empty:
        diario["pessoas"] = diario["pessoas"].astype(int)
        diario["Etapa"] = diario["etapa"].map(ETAPA_LABEL)

    # ── Compra: a ponte de identidade (hoje quase vazia, ver docstring) ─────
    # `identificaveis` é o teto do que dá pra atribuir: quem passou pelo fluxo E
    # deixou telefone em algum evento. `compraram` é quem, além disso, aparece em
    # `compras` com compra no período ou depois do primeiro contato.
    ponte = _read("""
        with ev as (
          select distinct nullif(telefone_norm, '') as tel
          from public.manychat_eventos
          where fluxo = '{fluxo}'
            and (evento_em at time zone 'America/Sao_Paulo')::date
                between '{ini}' and '{fim}'
        )
        select
          (select count(*) from ev where tel is not null) as identificaveis,
          (select count(distinct c.telefone_norm)
             from public.compras c
             join ev on ev.tel = c.telefone_norm) as compraram,
          (select coalesce(sum(c.valor), 0)
             from public.compras c
             join ev on ev.tel = c.telefone_norm) as receita
    """.format(**per))
    if ponte.empty:
        identificaveis = compraram = 0
        receita = 0.0
    else:
        linha = ponte.iloc[0]
        identificaveis = int(linha["identificaveis"] or 0)
        compraram = int(linha["compraram"] or 0)
        receita = float(linha["receita"] or 0.0)

    # ── Outros fluxos de boas-vindas, como contexto ────────────────────────
    outros = _read("""
        select fluxo, etapa,
               count(distinct coalesce(nullif(subscriber_id, ''),
                                       nullif(telefone_norm, ''))) as pessoas
        from public.manychat_eventos
        where fluxo in ({slugs})
          and (evento_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
        group by fluxo, etapa
        order by fluxo, pessoas desc
    """.format(slugs=", ".join(f"'{s}'" for s in OUTROS_SLUGS), **per))
    if not outros.empty:
        outros["pessoas"] = outros["pessoas"].astype(int)
        outros["Fluxo"] = outros["fluxo"].map(OUTROS_SLUGS).fillna(outros["fluxo"])

    # ── Compra por UTM: a atribuição que não depende de identidade ─────────
    # Gravado a partir da migration 0020 + deploy do payt-webhook. Antes disso a
    # coluna é nula para todo mundo, e a página diz isso em vez de mostrar zero.
    # Agrupa pelo conjunto de parâmetros como veio — não por campos fixos. A Payt
    # usa `src`/`sck`/`xcod` (a mesma família do Hotmart), então travar a leitura
    # em utm_source/utm_campaign deixaria a tabela inteira em "(sem source)".
    utms = _read("""
        select utm::text                             as utm_json,
               utm::text ilike '%{etiqueta}%'        as do_fluxo,
               count(*)                              as compras,
               coalesce(sum(valor), 0)               as receita
        from public.compras
        where utm is not null
          and (compra_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
        group by 1, 2
        order by compras desc
    """.format(etiqueta=UTM_FLUXO, **per))
    if not utms.empty:
        import json as _json

        def _rotulo(txt: str) -> str:
            """`{"src": "v4-manychat-dm"}` vira `src=v4-manychat-dm`."""
            try:
                d = _json.loads(txt) or {}
            except Exception:
                return txt[:80]
            return " · ".join(f"{k}={v}" for k, v in sorted(d.items())) or "(vazio)"

        utms["compras"] = utms["compras"].astype(int)
        utms["receita"] = utms["receita"].astype(float)
        utms["do_fluxo"] = utms["do_fluxo"].astype(bool)
        utms["Origem"] = utms["utm_json"].map(_rotulo)

    com_utm = _read("""
        select count(*) as n
        from public.compras
        where utm is not null
          and (compra_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
    """.format(**per))
    total_com_utm = int(com_utm.iloc[0]["n"]) if not com_utm.empty else 0

    total_compras = _read("""
        select count(*) as n
        from public.compras
        where (compra_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
    """.format(**per))
    total_compras = int(total_compras.iloc[0]["n"]) if not total_compras.empty else 0

    return {
        "funil": funil,
        "utms": utms,
        "utm_etiqueta": UTM_FLUXO,
        "compras_com_utm": total_com_utm,
        "compras_periodo": total_compras,
        "recebeu": recebeu,
        "entrou": entrou,
        "engajou": engajou,
        "diario": diario,
        "identificaveis": identificaveis,
        "compraram": compraram,
        "receita": receita,
        "outros": outros,
    }
