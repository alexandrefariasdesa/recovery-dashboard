"""
processors/aula_eventos.py
================================================================================
O que aconteceu DENTRO do webinário — a metade que faltava do funil da aula.

A página `Aula` mostra o que a gente MANDOU (convites_aula / convites_aula_envios).
Esta mostra o que a pessoa FEZ depois de receber: entrou, ficou quanto tempo,
clicou na oferta. A fonte é `aula_eventos`, que aceita qualquer webhook da
plataforma sem conhecer os nomes de antemão (ver 0015).

Por isso o processor é ESCRITO PARA NÃO SABER os tipos. Nada aqui declara
"entrou_sala" ou "clicou_oferta": ele lê o catálogo do banco e monta a página
com o que apareceu. Um webhook novo cadastrado no painel da Applive vira uma
linha nova aqui, sem deploy.

O número que mais importa não é volume, é `sem_chave`: evento que chega sem
telefone e sem e-mail não cruza com ninguém e não serve pra decidir mensagem.
É a diferença entre um webhook que vale a pena e um que só enche a tabela.
"""
from datetime import date

import pandas as pd

from clients.postgres import _read


def _catalogo() -> pd.DataFrame:
    """Quais webhooks chegaram — a lista que a gente não tinha de antemão."""
    df = _read("select * from v_aula_eventos_catalogo order by total desc")
    if df.empty:
        return df
    df["identificavel_pct"] = (
        100.0 * (df["total"] - df["sem_chave"]) / df["total"].replace(0, pd.NA)
    ).round(1)
    return df


def _por_dia(ini: str, fim: str) -> pd.DataFrame:
    return _read(f"""
        select (evento_em at time zone 'America/Sao_Paulo')::date as dia,
               evento, count(*) as n
        from aula_eventos
        where (evento_em at time zone 'America/Sao_Paulo')::date between '{ini}' and '{fim}'
        group by 1, 2
        order by 1, n desc
    """)


def _eventos(ini: str, fim: str) -> pd.DataFrame:
    """As linhas do período, já cruzadas com quem foi convidada."""
    df = _read(f"""
        select evento_em, evento, nome, telefone_core, email, sala, aula_data,
               duracao_seg, url, valor, veio_do_convite
        from v_aula_eventos_pessoa
        where (evento_em at time zone 'America/Sao_Paulo')::date between '{ini}' and '{fim}'
        order by evento_em desc
    """)
    if df.empty:
        return df
    df["evento_em"] = (
        pd.to_datetime(df["evento_em"], utc=True, errors="coerce")
        .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
    )
    df["duracao_min"] = (
        pd.to_numeric(df["duracao_seg"], errors="coerce") / 60.0
    ).round(1)
    return df


def _pessoas(ini: str, fim: str) -> pd.DataFrame:
    """Uma linha por pessoa, com os eventos dela virando colunas.

    É a forma que responde "quem entrou e não comprou" — a pergunta que motivou
    cadastrar os webhooks. A pivotagem é dinâmica de propósito: as colunas são
    os eventos que existirem, não uma lista fixa.
    """
    df = _read(f"""
        select chave, max(nome) as nome, max(telefone_core) as telefone_core,
               max(email) as email, evento, count(*) as n,
               min(evento_em) as primeiro, max(evento_em) as ultimo,
               max(duracao_seg) as duracao_seg,
               bool_or(veio_do_convite) as veio_do_convite
        from v_aula_eventos_pessoa
        where chave is not null
          and (evento_em at time zone 'America/Sao_Paulo')::date between '{ini}' and '{fim}'
        group by chave, evento
    """)
    if df.empty:
        return df

    base = (df.groupby("chave")
              .agg(nome=("nome", "max"), telefone_core=("telefone_core", "max"),
                   email=("email", "max"),
                   veio_do_convite=("veio_do_convite", "max"),
                   duracao_min=("duracao_seg", lambda s: round((s.max() or 0) / 60.0, 1)),
                   ultimo=("ultimo", "max"))
              .reset_index())
    largo = df.pivot_table(index="chave", columns="evento", values="n",
                           aggfunc="sum", fill_value=0).reset_index()
    return base.merge(largo, on="chave", how="left")


def _cruzamento_compra(ini: str, fim: str) -> pd.DataFrame:
    """Quem apareceu no webinário e comprou depois — a leitura de dinheiro.

    Junta pelo telefone_core (a chave do sistema) contra `compras`, com a compra
    contando só se veio DEPOIS do evento. É o mesmo desenho da supressão da
    recuperação: a compra anterior não é mérito do que aconteceu na sala.
    """
    return _read(f"""
        with p as (
            select distinct evento, telefone_core
            from v_aula_eventos_pessoa
            where telefone_core is not null and telefone_core <> ''
              and (evento_em at time zone 'America/Sao_Paulo')::date between '{ini}' and '{fim}'
        ),
        ev as (
            select p.evento, p.telefone_core,
                   min(e.evento_em) as evento_em
            from p
            join v_aula_eventos_pessoa e
              on e.telefone_core = p.telefone_core and e.evento = p.evento
            group by 1, 2
        )
        select ev.evento,
               count(*) as pessoas,
               count(c.telefone_core) as compraram,
               round(100.0 * count(c.telefone_core) / nullif(count(*), 0), 1) as taxa_pct,
               round(coalesce(sum(c.valor), 0)::numeric, 2) as valor
        from ev
        left join lateral (
            select c.telefone_core, c.valor
            from compras c
            where c.telefone_core = ev.telefone_core
              and c.compra_em >= ev.evento_em
            order by c.compra_em
            limit 1
        ) c on true
        group by ev.evento
        order by pessoas desc
    """)


def build_aula_eventos(start_date: date, end_date: date) -> dict:
    ini, fim = start_date.isoformat(), end_date.isoformat()
    catalogo = _catalogo()

    return {
        "catalogo": catalogo,
        "eventos": _eventos(ini, fim),
        "por_dia": _por_dia(ini, fim),
        "pessoas": _pessoas(ini, fim),
        "compra": _cruzamento_compra(ini, fim) if not catalogo.empty else pd.DataFrame(),
        "vazio": catalogo.empty,
    }
