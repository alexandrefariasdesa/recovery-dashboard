"""
processors/funis.py
================================================================================
Os três funis que não tinham página própria: Aquisição, Boas-vindas e Grupo.

Ficam juntos porque compartilham a mesma forma — recorte por período, série
diária e um corte por categoria — e porque separar em três arquivos de 60 linhas
só espalharia a mesma consulta em três lugares.

**Grupo saiu da planilha.** Até 22/08 a página lia "[LEADS] ENTRADA NOS GRUPOS",
escrita pelo Make a partir do SendFlow, que parou de receber em 15/07: o painel
mostrava quase todo mundo como "não entrou" e a fila de pendentes crescia
sozinha. Agora a fonte é `grupo_entradas`, alimentada pelo endpoint `/grupo`.
"""
import pandas as pd
import streamlit as st

from clients.postgres import _read


def _sp(s):
    """timestamptz (UTC) → parede de relógio de São Paulo, sem fuso."""
    return (pd.to_datetime(s, utc=True, errors="coerce")
              .dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None))


# ── Aquisição ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def build_aquisicao(start_date, end_date) -> dict:
    """A venda de entrada: quanto entrou, de quantas pessoas, em que ritmo.

    Só `tipo='front'` — upsell tem página própria, e somar os dois aqui faria a
    mesma cliente contar duas vezes no "compradoras".
    """
    base = """
        select c.id, c.compra_em, c.nome, c.email, c.telefone, c.valor, c.produto
        from public.compras c
        where c.tipo = 'front'
          and (c.compra_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
    """.format(ini=start_date, fim=end_date)
    df = _read(base)
    if not df.empty:
        df["compra_em"] = _sp(df["compra_em"])
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
        df["dia"] = df["compra_em"].dt.date

    diario = (df.groupby("dia").agg(compradoras=("id", "size"), receita=("valor", "sum"))
                .reset_index()) if not df.empty else pd.DataFrame()
    if not diario.empty:
        diario["ticket"] = (diario["receita"] / diario["compradoras"]).round(2)

    # O valor da compra carrega o order bump embutido (a Payt manda o total), então
    # a distribuição de valores é o retrato mais próximo do mix de bump que existe.
    faixas = (df.groupby("valor").agg(compradoras=("id", "size")).reset_index()
                .sort_values("compradoras", ascending=False)) if not df.empty else pd.DataFrame()

    return {
        "base": df, "diario": diario, "faixas": faixas,
        "receita": float(df["valor"].sum()) if not df.empty else 0.0,
        "compradoras": int(len(df)),
    }


# ── Boas-vindas ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def build_boas_vindas(start_date, end_date) -> dict:
    """O motor de boas-vindas: o que ele fez com cada compra aprovada.

    `compra_id is not null` é o recorte certo — é o que separa o disparo que
    nasce de uma COMPRA do que nasce de um evento de recuperação.
    """
    q = """
        select d.id, d.tipo, d.status, coalesce(d.motivo,'') as motivo,
               d.criado_em, d.quando_enviar, d.enviado_em, d.telefone_core,
               c.nome, c.produto, c.valor
        from public.recuperacao_disparos d
        join public.compras c on c.id = d.compra_id
        where (d.criado_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
    """.format(ini=start_date, fim=end_date)
    df = _read(q)
    if not df.empty:
        for col in ("criado_em", "quando_enviar", "enviado_em"):
            df[col] = _sp(df[col])
        df["dia"] = df["criado_em"].dt.date
        df["atraso_min"] = ((df["enviado_em"] - df["quando_enviar"])
                            .dt.total_seconds() / 60).round(1)

    quadro = (df.pivot_table(index="tipo", columns="status", values="id",
                             aggfunc="count", fill_value=0).reset_index()
              ) if not df.empty else pd.DataFrame()
    diario = (df.groupby(["dia", "status"]).size().reset_index(name="n")
              ) if not df.empty else pd.DataFrame()

    cfg = _read("""
        select tipo, modo, coalesce(produto_like,'') as produto_like
        from public.recuperacao_config where origem = 'compra' order by tipo
    """)
    return {"base": df, "quadro": quadro, "diario": diario, "config": cfg}


# ── Grupo ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def build_grupo(start_date, end_date) -> dict:
    """Entrada em grupo no período + a taxa entre as compradoras do período.

    São duas perguntas diferentes e o painel precisa das duas: quantas pessoas
    entraram (o volume que a campanha trouxe) e que fatia das compradoras entrou
    (a taxa que diz se o grupo está sendo entregue direito).
    """
    entradas = _read("""
        select e.id, e.entrou_em, e.campanha, e.campanha_id, e.grupo,
               e.telefone, e.telefone_core
        from public.grupo_entradas e
        where (e.entrou_em at time zone 'America/Sao_Paulo')::date
              between '{ini}' and '{fim}'
    """.format(ini=start_date, fim=end_date))
    if not entradas.empty:
        entradas["entrou_em"] = _sp(entradas["entrou_em"])
        entradas["dia"] = entradas["entrou_em"].dt.date

    # Compradoras do período e se entraram — o mesmo lateral da página Upsell,
    # com o filtro de período ANTES do join (a view agregava a base inteira e
    # custava 79s).
    compradoras = _read("""
        with front as (
          select c.id, c.telefone_core, c.compra_em, c.valor, c.nome
          from public.compras c
          where c.tipo = 'front'
            and (c.compra_em at time zone 'America/Sao_Paulo')::date
                between '{ini}' and '{fim}'
        )
        select f.id, f.nome, f.compra_em, f.valor,
               (g.id is not null) as entrou, g.entrou_em, g.campanha, g.grupo
        from front f
        left join lateral (
          select ge.id, ge.entrou_em, ge.campanha, ge.grupo
          from public.grupo_entradas ge
          where ge.telefone_core = f.telefone_core
            and ge.entrou_em >= f.compra_em - interval '1 day'
          order by ge.entrou_em limit 1
        ) g on true
    """.format(ini=start_date, fim=end_date))
    if not compradoras.empty:
        compradoras["compra_em"] = _sp(compradoras["compra_em"])
        compradoras["entrou_em"] = _sp(compradoras["entrou_em"])
        compradoras["valor"] = pd.to_numeric(compradoras["valor"], errors="coerce").fillna(0.0)
        compradoras["dia"] = compradoras["compra_em"].dt.date

    por_campanha = (
        entradas.groupby(["campanha", "grupo"], dropna=False).size()
        .reset_index(name="entradas").sort_values("entradas", ascending=False)
    ) if not entradas.empty else pd.DataFrame()

    taxa_diaria = (
        compradoras.groupby("dia").agg(compradoras=("id", "size"), entraram=("entrou", "sum"))
        .reset_index()
    ) if not compradoras.empty else pd.DataFrame()
    if not taxa_diaria.empty:
        taxa_diaria["taxa"] = (taxa_diaria["entraram"] / taxa_diaria["compradoras"] * 100).round(1)

    return {"entradas": entradas, "compradoras": compradoras,
            "por_campanha": por_campanha, "taxa_diaria": taxa_diaria}
