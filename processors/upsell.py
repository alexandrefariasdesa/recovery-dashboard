"""
processors/upsell.py
================================================================================
O que a compradora do Posições faz DEPOIS de comprar: entrou no grupo? levou
upsell? São as duas perguntas do pós-compra, e as duas se respondem pelo mesmo
telefone — por isso vivem na mesma página.

**Trocou de fonte em 22/08/2026.** Antes, a entrada em grupo vinha da planilha
"[LEADS] ENTRADA NOS GRUPOS", escrita pelo Make a partir do SendFlow, e o
cruzamento era feito em Python comparando variantes do telefone (com/sem o 9).
A planilha parou de receber em 15/07 — a página mostrava taxa zero como se
ninguém entrasse mais em grupo nenhum. Agora o SendFlow posta direto no
endpoint `/grupo` do worker, que grava em `grupo_entradas`, e o cruzamento é um
join por `telefone_core` (o phone_core do banco já colapsa a variante do 9).

Por que a consulta não usa as views `v_grupo_compradoras`/`v_upsell_por_compra`:
elas agregam as 38 mil compras antes de qualquer filtro, e a página levava 79
segundos. Aqui o período entra ANTES, num CTE, e os dois laterais rodam só
sobre as linhas do período — 0,6s pra uma semana. As views continuam valendo
pra análise solta, onde a lentidão não incomoda.
"""
from datetime import date

import pandas as pd
import psycopg2

import config


_SQL = """
with front as (
  select c.id, c.nome, c.email, c.telefone, c.telefone_core,
         c.compra_em, c.valor, c.produto
  from public.compras c
  where c.tipo = 'front'
    and c.produto ilike %(produto)s
    and (c.compra_em at time zone 'America/Sao_Paulo')::date between %(ini)s and %(fim)s
)
select f.nome, f.email, f.telefone, f.compra_em, f.valor, f.produto,
       (g.id is not null) as entrou_no_grupo,
       g.entrou_em as data_entrada_grupo,
       g.campanha, g.grupo,
       coalesce(u.upsells, 0)     as upsells,
       coalesce(u.valor_upsell, 0) as valor_upsell
from front f
-- A primeira entrada em grupo dela. A janela abre 1 dia ANTES da compra porque
-- o link do grupo circula junto do checkout: quem entra e paga depois não pode
-- contar como "não entrou".
left join lateral (
  select ge.id, ge.entrou_em, ge.campanha, ge.grupo
  from public.grupo_entradas ge
  where ge.telefone_core = f.telefone_core
    and ge.entrou_em >= f.compra_em - interval '1 day'
  order by ge.entrou_em
  limit 1
) g on true
-- Upsells dos 7 dias seguintes: é a janela em que a oferta ainda está de pé.
left join lateral (
  select count(*) as upsells, coalesce(sum(up.valor), 0) as valor_upsell
  from public.compras up
  where up.tipo = 'upsell'
    and up.telefone_core = f.telefone_core
    and up.compra_em >= f.compra_em
    and up.compra_em <  f.compra_em + interval '7 days'
) u on true
order by f.compra_em desc
"""


def build_upsell_dataframe(start_date: date, end_date: date) -> pd.DataFrame:
    conn = psycopg2.connect(
        host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
        password=config.PG_PASSWORD, dbname=config.PG_DBNAME, connect_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute(_SQL, {
            "produto": f"%{config.LOW_TICKET_PRODUCT[:10]}%",
            "ini": start_date, "fim": end_date,
        })
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df

    # timestamptz (UTC) → parede de relógio de São Paulo, igual ao resto do painel.
    for c in ("compra_em", "data_entrada_grupo"):
        df[c] = (pd.to_datetime(df[c], utc=True, errors="coerce")
                   .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None))
    for c in ("valor", "valor_upsell"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["upsells"] = pd.to_numeric(df["upsells"], errors="coerce").fillna(0).astype(int)
    df["ticket_total"] = df["valor"] + df["valor_upsell"]
    return df
