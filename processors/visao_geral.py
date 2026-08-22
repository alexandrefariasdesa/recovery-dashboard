"""
processors/visao_geral.py
================================================================================
O topo de cada funil, lado a lado — a página que responde "como foi a semana?"
antes de qualquer detalhe.

Três decisões que explicam o formato:

**Dinheiro na frente.** Cada cartão lidera com o valor que aquele funil moveu no
período. Volume e taxa entram como apoio. Funil que não move dinheiro por
natureza (boas-vindas, aula) lidera com o próprio número de entrega, e o cartão
diz isso — inventar uma receita pra ele seria pior que admitir que não tem.

**Sempre contra o período anterior.** Um número sozinho não informa: R$ 4.312
recuperados é bom ou ruim? A comparação é com a janela imediatamente anterior,
do mesmo tamanho — se o filtro é de 7 dias, compara com os 7 dias anteriores.

**Uma consulta por funil, com o período dentro.** Nada de view agregando a base
inteira pra depois filtrar (foi o que fez a página Upsell levar 79s). Cada
função recebe as datas e devolve os números dos DOIS períodos de uma vez.
"""
from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd
import streamlit as st

from clients.postgres import _read


@dataclass
class Cartao:
    """Um funil na visão geral. `valor` é o número grande; o resto é apoio."""
    chave: str
    titulo: str
    valor: float
    formato: str                 # "dinheiro" | "numero"
    legenda: str                 # o que o número grande significa
    apoios: list = field(default_factory=list)
    anterior: float = None
    pagina: str = None           # url_path da página de detalhe
    nota: str = None             # ressalva honesta (fonte parcial, motor off...)
    estado: str = "ok"           # ok | espera | desligado

    @property
    def variacao(self):
        """% contra o período anterior. None quando não dá pra comparar.

        `estado != 'ok'` também devolve None de propósito: quando a fonte é
        parcial (o grupo só registra desde 22/08) ou o motor está em simulado, a
        variação existe aritmeticamente mas não significa nada — e um "+327%"
        falso é pior que nenhum número.
        """
        if self.anterior in (None, 0) or self.estado != "ok":
            return None
        return (float(self.valor) - float(self.anterior)) / abs(float(self.anterior)) * 100


def _janela_anterior(ini, fim):
    dias = (fim - ini).days + 1
    return ini - timedelta(days=dias), ini - timedelta(days=1)


def _um(df, col, default=0):
    if df is None or df.empty or col not in df.columns:
        return default
    v = df.iloc[0][col]
    return default if pd.isna(v) else v


def _br(n):
    return f"{int(n):,}".replace(",", ".")


def _reais(v):
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# -- Cada funil --------------------------------------------------------------

def _aquisicao(ini, fim, pini, pfim):
    q = """
        select
          coalesce(sum(valor) filter (where p = 'atual'), 0)    as receita,
          count(*)            filter (where p = 'atual')        as compradoras,
          coalesce(sum(valor) filter (where p = 'anterior'), 0) as receita_ant
        from (
          select c.valor,
                 case when (c.compra_em at time zone 'America/Sao_Paulo')::date
                           between '{ini}' and '{fim}' then 'atual' else 'anterior' end as p
          from public.compras c
          where c.tipo = 'front'
            and (c.compra_em at time zone 'America/Sao_Paulo')::date between '{pini}' and '{fim}'
        ) t
    """.format(ini=ini, fim=fim, pini=pini)
    d = _read(q)
    receita = float(_um(d, "receita"))
    n = int(_um(d, "compradoras"))
    return Cartao(
        chave="aquisicao", titulo="Aquisição", valor=receita, formato="dinheiro",
        legenda="em vendas de entrada", pagina="aquisicao",
        anterior=float(_um(d, "receita_ant")),
        apoios=[("compradoras", _br(n)),
                ("ticket médio", _reais(receita / n) if n else "—")],
    )


def _recuperacao(ini, fim, pini, pfim):
    q = """
        select
          coalesce(sum(valor_recuperado) filter (where p = 'atual'), 0)    as recuperado,
          count(*) filter (where p = 'atual')                              as eventos,
          count(*) filter (where p = 'atual' and converteu)                as converteram,
          coalesce(sum(valor_recuperado) filter (where p = 'anterior'), 0) as recuperado_ant
        from (
          select v.valor_recuperado, v.converteu,
                 case when (v.evento_em at time zone 'America/Sao_Paulo')::date
                           between '{ini}' and '{fim}' then 'atual' else 'anterior' end as p
          from public.v_recovery_conversao v
          where (v.evento_em at time zone 'America/Sao_Paulo')::date between '{pini}' and '{fim}'
        ) t
    """.format(ini=ini, fim=fim, pini=pini)
    d = _read(q)
    eventos = int(_um(d, "eventos"))
    conv = int(_um(d, "converteram"))
    taxa = conv / eventos * 100 if eventos else 0.0
    return Cartao(
        chave="recuperacao", titulo="Recuperação", valor=float(_um(d, "recuperado")),
        formato="dinheiro", legenda="recuperado depois do evento", pagina="recuperacao",
        anterior=float(_um(d, "recuperado_ant")),
        apoios=[("eventos", _br(eventos)), ("converteram", f"{taxa:.1f}%")],
    )


def _upsell(ini, fim, pini, pfim):
    q = """
        select
          coalesce(sum(valor) filter (where p = 'atual'), 0)    as receita,
          count(*)            filter (where p = 'atual')        as vendas,
          coalesce(sum(valor) filter (where p = 'anterior'), 0) as receita_ant
        from (
          select c.valor,
                 case when (c.compra_em at time zone 'America/Sao_Paulo')::date
                           between '{ini}' and '{fim}' then 'atual' else 'anterior' end as p
          from public.compras c
          where c.tipo = 'upsell'
            and (c.compra_em at time zone 'America/Sao_Paulo')::date between '{pini}' and '{fim}'
        ) t
    """.format(ini=ini, fim=fim, pini=pini)
    d = _read(q)
    receita = float(_um(d, "receita"))
    vendas = int(_um(d, "vendas"))
    c = Cartao(
        chave="upsell", titulo="Upsell", valor=receita, formato="dinheiro",
        legenda="em vendas posteriores", pagina="upsell",
        anterior=float(_um(d, "receita_ant")),
        apoios=[("vendas", _br(vendas)),
                ("ticket", _reais(receita / vendas) if vendas else "—")],
    )
    if vendas == 0:
        c.estado = "espera"
        c.nota = ("Nenhum upsell registrado no período. Só entra a oferta que "
                  "tiver a URL com `&venda=upsell` cadastrada na Payt.")
    return c


def _grupo(ini, fim, pini, pfim):
    """Dinheiro aqui é a receita das compradoras que ENTRARAM no grupo — é o
    valor que o grupo está segurando, e o que se perde quando a taxa cai."""
    q = """
        with front as (
          select c.id, c.telefone_core, c.compra_em, c.valor,
                 case when (c.compra_em at time zone 'America/Sao_Paulo')::date
                           between '{ini}' and '{fim}' then 'atual' else 'anterior' end as p
          from public.compras c
          where c.tipo = 'front'
            and (c.compra_em at time zone 'America/Sao_Paulo')::date between '{pini}' and '{fim}'
        )
        select
          coalesce(sum(f.valor) filter (where f.p='atual' and g.id is not null), 0)    as receita_no_grupo,
          count(*)    filter (where f.p='atual')                                       as compradoras,
          count(g.id) filter (where f.p='atual')                                       as entraram,
          coalesce(sum(f.valor) filter (where f.p='anterior' and g.id is not null), 0) as receita_ant
        from front f
        left join lateral (
          select ge.id from public.grupo_entradas ge
          where ge.telefone_core = f.telefone_core
            and ge.entrou_em >= f.compra_em - interval '1 day'
          limit 1
        ) g on true
    """.format(ini=ini, fim=fim, pini=pini)
    d = _read(q)
    compradoras = int(_um(d, "compradoras"))
    entraram = int(_um(d, "entraram"))
    taxa = entraram / compradoras * 100 if compradoras else 0.0
    c = Cartao(
        chave="grupo", titulo="Grupo", valor=float(_um(d, "receita_no_grupo")),
        formato="dinheiro", legenda="em compras de quem entrou no grupo", pagina="grupo",
        anterior=float(_um(d, "receita_ant")),
        apoios=[("entraram", f"{entraram} de {_br(compradoras)}"),
                ("taxa de entrada", f"{taxa:.1f}%")],
    )
    if pd.Timestamp(ini) < pd.Timestamp("2026-08-22"):
        c.estado = "espera"
        c.nota = ("Taxa subestimada: a entrada em grupo só é registrada a partir "
                  "de 22/08/2026 13h16, quando o SendFlow passou a postar aqui.")
    return c


def _boas_vindas(ini, fim, pini, pfim):
    """Sem dinheiro próprio: a boas-vindas não vende, ela entrega. O número
    grande é a entrega, e o cartão diz que é entrega, não receita."""
    q = """
        select
          count(*) filter (where p='atual' and status in ('enviado','simulado'))    as entregues,
          count(*) filter (where p='atual' and status='enviado')                    as enviadas,
          count(*) filter (where p='atual' and status='erro')                       as erros,
          count(*) filter (where p='anterior' and status in ('enviado','simulado')) as entregues_ant
        from (
          select d.status,
                 case when (d.criado_em at time zone 'America/Sao_Paulo')::date
                           between '{ini}' and '{fim}' then 'atual' else 'anterior' end as p
          from public.recuperacao_disparos d
          where d.compra_id is not null
            and (d.criado_em at time zone 'America/Sao_Paulo')::date between '{pini}' and '{fim}'
        ) t
    """.format(ini=ini, fim=fim, pini=pini)
    d = _read(q)
    entregues = int(_um(d, "entregues"))
    enviadas = int(_um(d, "enviadas"))
    erros = int(_um(d, "erros"))
    c = Cartao(
        chave="boas_vindas", titulo="Boas-vindas", valor=entregues, formato="numero",
        legenda="compras atendidas pelo motor", pagina="boas-vindas",
        anterior=int(_um(d, "entregues_ant")),
        apoios=[("enviadas de verdade", _br(enviadas)), ("erros", _br(erros))],
    )
    if enviadas == 0 and entregues > 0:
        c.estado = "espera"
        c.nota = ("Em modo simulado: o motor registra o que mandaria, e quem fala "
                  "com a cliente ainda é o cenário de compra aprovada no Make.")
    return c


def _aula(ini, fim, pini, pfim):
    q = """
        select
          count(*) filter (where p='atual' and status='enviada')    as enviadas,
          count(*) filter (where p='anterior' and status='enviada') as enviadas_ant,
          (select ativo from public.convites_aula_config limit 1)   as ativo
        from (
          select e.status,
                 case when (e.criada_em at time zone 'America/Sao_Paulo')::date
                           between '{ini}' and '{fim}' then 'atual' else 'anterior' end as p
          from public.convites_aula_envios e
          where (e.criada_em at time zone 'America/Sao_Paulo')::date between '{pini}' and '{fim}'
        ) t
    """.format(ini=ini, fim=fim, pini=pini)
    d = _read(q)
    enviadas = int(_um(d, "enviadas"))
    ativo = bool(_um(d, "ativo", False))
    c = Cartao(
        chave="aula", titulo="Convite da aula", valor=enviadas, formato="numero",
        legenda="convites enviados", pagina="aula",
        anterior=int(_um(d, "enviadas_ant")),
        apoios=[("motor", "ligado" if ativo else "desligado")],
    )
    if not ativo:
        c.estado = "desligado"
        c.nota = ("`convites_aula_config.ativo` está false — os crons batem na hora "
                  "certa, mas a edge function não manda nada.")
    return c


@st.cache_data(ttl=120, show_spinner=False)
def build_visao_geral(start_date, end_date):
    pini, pfim = _janela_anterior(start_date, end_date)
    cartoes, erros = [], []
    for fn in (_aquisicao, _recuperacao, _upsell, _grupo, _boas_vindas, _aula):
        try:
            cartoes.append(fn(start_date, end_date, pini, pfim))
        except Exception as exc:   # um funil quebrado não derruba a página
            erros.append(f"{fn.__name__.strip('_')}: {str(exc)[:160]}")
    return {"cartoes": cartoes, "erros": erros,
            "periodo": (start_date, end_date), "anterior": (pini, pfim)}
