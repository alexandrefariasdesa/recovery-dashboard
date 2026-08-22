-- =============================================================================
-- 0012_grupo_taxa.sql — a taxa que o endpoint /grupo existe pra medir
--
-- "De cada 100 compradoras do Posições, quantas entram no grupo?" O cruzamento
-- é por `telefone_core`, a mesma chave canônica do resto do banco.
--
-- Janela: conta a entrada a partir de 1 DIA ANTES da compra. Parece estranho,
-- mas é o caso real — o link do grupo circula junto do checkout, e quem entra
-- primeiro e paga depois entraria como "não entrou" numa regra estritamente
-- posterior. Um dia é folga suficiente pra isso sem começar a colar entradas
-- antigas em compras novas.
--
-- A view fica no grão da COMPRA (uma linha por compradora, com a primeira
-- entrada dela se houver). Assim a taxa é um `avg(entrou::int)` em qualquer
-- recorte — por dia, por campanha, por grupo — em vez de um número já mastigado.
-- Idempotente.
-- =============================================================================

create or replace view public.v_grupo_compradoras as
select
  c.id            as compra_id,
  c.compra_em,
  c.nome,
  c.telefone_core,
  c.produto,
  c.valor,
  g.id            as entrada_id,
  g.entrou_em,
  g.grupo,
  g.campanha,
  (g.id is not null) as entrou,
  case when g.id is not null
       then extract(epoch from (g.entrou_em - c.compra_em)) / 3600.0
  end             as horas_ate_entrar
from public.compras c
left join lateral (
  select ge.*
  from public.grupo_entradas ge
  where ge.telefone_core = c.telefone_core
    and ge.entrou_em >= c.compra_em - interval '1 day'
  order by ge.entrou_em
  limit 1
) g on true
where c.produto ilike '%posi%';

comment on view public.v_grupo_compradoras is
  'Uma linha por compradora de Posições, com a primeira entrada em grupo dela '
  '(a partir de 1 dia antes da compra). taxa = avg(entrou::int).';
