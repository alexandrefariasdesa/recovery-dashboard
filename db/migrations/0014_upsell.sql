-- =============================================================================
-- 0014_upsell.sql — upsell deixa de ser receita invisível
--
-- A operação roda VÁRIOS upsells (Protocolo do Prazer, Safada na Hora Certa,
-- entre outros). Nenhum deles existe hoje: `compras` tem 8.300 linhas em 30
-- dias, todas "Posições Secretas!", e a aba Leads guarda só produto + order
-- bump. O upsell é uma transação própria na Payt, com `type: "upsell"` e
-- `transaction.upsell_from` apontando pra compra que o gerou.
--
-- POR QUE UMA COLUNA E NÃO UMA TABELA À PARTE: `recuperacao_disparos.compra_id`
-- tem FK pra `compras`, e é assim que a boas-vindas de um upsell é agendada
-- (o Protocolo tem fluxo próprio). Uma tabela separada obrigaria a duplicar
-- esse caminho inteiro. Com `tipo` como discriminador, o motor não muda uma
-- linha e as métricas filtram — que é o que "separado" precisa significar aqui.
--
-- A ARMADILHA que isso desarma: `v_recovery_conversao` pega a ÚLTIMA compra do
-- telefone. Sem filtro, um upsell de R$ 27 chegando depois substituiria os
-- R$ 76,90 do front como "valor recuperado" — a recuperação passaria a valer
-- menos justamente quando a cliente comprou mais.
-- Idempotente.
-- =============================================================================

alter table public.compras
  add column if not exists tipo text not null default 'front';
alter table public.compras
  add column if not exists upsell_de text;   -- transaction_id da compra de origem

do $$ begin
  alter table public.compras
    add constraint compras_tipo_chk check (tipo in ('front', 'upsell'));
exception when duplicate_object then null; end $$;

create index if not exists compras_tipo_idx on public.compras (tipo, compra_em);

comment on column public.compras.tipo is
  'front = compra de entrada (é o que conta como conversão e como receita '
  'recuperada) · upsell = venda posterior, transação própria na Payt.';

-- ── A conversão volta a olhar só o front ─────────────────────────────────────
create or replace view public.v_recovery_conversao as
select
  re.id,
  re.evento_em,
  re.tipo,
  re.nome,
  re.telefone,
  re.valor,
  (c.compra_em is not null
     and (c.compra_em at time zone 'America/Sao_Paulo')::date
         >= (re.evento_em at time zone 'America/Sao_Paulo')::date
  ) as converteu,
  case when c.compra_em is not null
        and (c.compra_em at time zone 'America/Sao_Paulo')::date
            >= (re.evento_em at time zone 'America/Sao_Paulo')::date
       then c.valor else 0 end as valor_recuperado,
  c.compra_em  as data_pagamento,
  c.produto    as produto_comprado
from public.recovery_events re
left join lateral (
  select valor, compra_em, produto
  from public.compras c
  where c.telefone_core = re.telefone_core
    and c.tipo = 'front'          -- <- upsell não é conversão de recuperação
  order by c.compra_em desc
  limit 1
) c on re.telefone_core is not null and re.telefone_core <> '';

-- ── Take-rate de upsell: quem comprou o front levou o quê ────────────────────
-- Uma linha por compra de entrada, com os upsells pendurados. Serve pra duas
-- perguntas: quantos % levam upsell, e quanto o ticket real difere do anunciado.
create or replace view public.v_upsell_por_compra as
select
  f.id                                   as compra_id,
  f.compra_em,
  f.nome,
  f.telefone_core,
  f.produto                              as produto_front,
  f.valor                                as valor_front,
  count(u.id)                            as upsells,
  coalesce(sum(u.valor), 0)              as valor_upsell,
  f.valor + coalesce(sum(u.valor), 0)    as ticket_total,
  array_remove(array_agg(u.produto order by u.compra_em), null) as produtos_upsell
from public.compras f
left join public.compras u
       on u.tipo = 'upsell'
      and u.telefone_core = f.telefone_core
      and u.compra_em >= f.compra_em
      and u.compra_em <  f.compra_em + interval '7 days'
where f.tipo = 'front'
group by f.id, f.compra_em, f.nome, f.telefone_core, f.produto, f.valor;

comment on view public.v_upsell_por_compra is
  'Uma linha por compra de entrada com os upsells dos 7 dias seguintes. '
  'take-rate = avg((upsells > 0)::int).';

-- A taxa de entrada em grupo também é sobre a compradora do front, não sobre
-- quem levou upsell — senão a mesma pessoa entraria duas vezes na base.
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
where c.produto ilike '%posi%' and c.tipo = 'front';
