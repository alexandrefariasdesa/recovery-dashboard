-- =============================================================================
-- 0009_compra_aprovada.sql — boas-vindas de compra aprovada no mesmo motor
--
-- Até aqui o motor (0008) só sabia nascer de `recovery_events` (PIX, boleto,
-- carrinho). A boas-vindas nasce de outro lugar: a tabela `compras`, que o
-- `payt-webhook` já preenche. Então a fila ganha uma segunda origem em vez de
-- um motor paralelo — mesma máquina, mesmo modo de teste, mesmo painel.
--
--   origem = 'evento'  -> lê de recovery_events, casa por `tipo`
--   origem = 'compra'  -> lê de compras, casa por `produto_like`
--
-- A supressão ("já comprou, cancela") continua valendo SÓ pra origem 'evento':
-- numa boas-vindas a compra é o gatilho, não o motivo de cancelar.
--
-- ATENÇÃO: `desde` é a trava. Sem ela, ligar isso dispararia em cima de 38 mil
-- compras históricas. Os dois tipos novos entram com desde = agora.
-- Idempotente.
-- =============================================================================

-- ── Config ganha origem e casamento por produto ──────────────────────────────
alter table public.recuperacao_config
  add column if not exists origem text not null default 'evento',
  add column if not exists produto_like text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'recuperacao_config_origem_ck') then
    alter table public.recuperacao_config
      add constraint recuperacao_config_origem_ck check (origem in ('evento', 'compra'));
  end if;
end $$;

comment on column public.recuperacao_config.origem is
  'De onde o disparo nasce: evento (recovery_events) ou compra (compras).';
comment on column public.recuperacao_config.produto_like is
  'Só pra origem=compra: filtro ILIKE no produto da compra (ex.: %posi%).';

-- ── A fila passa a aceitar as duas origens ───────────────────────────────────
alter table public.recuperacao_disparos
  add column if not exists compra_id bigint references public.compras (id) on delete cascade;

alter table public.recuperacao_disparos alter column evento_id drop not null;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'recuperacao_disparos_origem_ck') then
    alter table public.recuperacao_disparos
      add constraint recuperacao_disparos_origem_ck
      check (num_nonnulls(evento_id, compra_id) = 1);
  end if;
end $$;

create unique index if not exists recuperacao_disparos_compra_etapa_uidx
  on public.recuperacao_disparos (compra_id, etapa) where compra_id is not null;

-- ── Os dois tipos de boas-vindas ─────────────────────────────────────────────
-- Começam em 'simulado' (registra sem enviar) e com a trava no agora, pra rodar
-- em paralelo com o Make sem tocar em ninguém e sem pegar histórico.
insert into public.recuperacao_config (tipo, modo, origem, produto_like, desde)
values
  ('compra_posicoes',  'simulado', 'compra', '%posi%',      now()),
  ('compra_protocolo', 'simulado', 'compra', '%protocolo%', now())
on conflict (tipo) do nothing;

insert into public.recuperacao_etapas (tipo, etapa, ordem, atraso, template, flow_ns) values
  ('compra_posicoes',  'boas_vindas', 1, '1 minute', null, 'content20251119113753_477102'),
  ('compra_protocolo', 'boas_vindas', 1, '1 minute', null, 'content20260612200553_387315')
on conflict (tipo, etapa) do nothing;

-- ── Agendador: agora varre as duas origens ───────────────────────────────────
create or replace function public.agendar_recuperacoes(p_limite int default 500)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n_ev integer := 0;
  n_co integer := 0;
begin
  -- Origem 'evento': PIX, boleto, carrinho.
  insert into public.recuperacao_disparos
    (evento_id, tipo, etapa, telefone_core, quando_enviar)
  select ev.id, ev.tipo, et.etapa, ev.telefone_core, ev.evento_em + et.atraso
  from public.recovery_events ev
  join public.recuperacao_config cfg on cfg.tipo = ev.tipo and cfg.origem = 'evento'
  join public.recuperacao_etapas et  on et.tipo  = ev.tipo and et.ativo
  where cfg.modo <> 'off'
    and cfg.desde is not null
    and ev.evento_em >= cfg.desde
    and coalesce(ev.telefone_core, '') <> ''
    and not exists (
      select 1 from public.recuperacao_disparos d
      where d.evento_id = ev.id and d.etapa = et.etapa
    )
  order by ev.evento_em
  limit p_limite
  on conflict do nothing;
  get diagnostics n_ev = row_count;

  -- Origem 'compra': boas-vindas, casando o produto.
  insert into public.recuperacao_disparos
    (compra_id, tipo, etapa, telefone_core, quando_enviar)
  select c.id, cfg.tipo, et.etapa, c.telefone_core, c.compra_em + et.atraso
  from public.compras c
  join public.recuperacao_config cfg
    on cfg.origem = 'compra'
   and cfg.produto_like is not null
   and c.produto ilike cfg.produto_like
  join public.recuperacao_etapas et on et.tipo = cfg.tipo and et.ativo
  where cfg.modo <> 'off'
    and cfg.desde is not null
    and c.compra_em >= cfg.desde
    and coalesce(c.telefone_core, '') <> ''
    and not exists (
      select 1 from public.recuperacao_disparos d
      where d.compra_id = c.id and d.etapa = et.etapa
    )
  order by c.compra_em
  limit p_limite
  on conflict do nothing;
  get diagnostics n_co = row_count;

  return n_ev + n_co;
end;
$$;

-- ── Supressão: só pra origem 'evento' ────────────────────────────────────────
-- Explícito no where: numa boas-vindas a compra É o gatilho.
create or replace function public.cancelar_recuperacoes_compradas()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  update public.recuperacao_disparos d
     set status = 'cancelado', motivo = 'ja comprou'
    from public.recovery_events ev
   where ev.id = d.evento_id
     and d.compra_id is null
     and d.status = 'agendado'
     and exists (
       select 1 from public.compras c
        where c.telefone_core = d.telefone_core
          and c.compra_em >= ev.evento_em
     );
  get diagnostics n = row_count;
  return n;
end;
$$;

-- ── Fila: telefone/nome/valor vêm da origem certa ────────────────────────────
drop function if exists public.fila_recuperacao(int, int);

create or replace function public.fila_recuperacao(
  p_limite         int default 80,
  p_max_tentativas int default 4
)
returns table (
  disparo_id    bigint,
  tipo          text,
  etapa         text,
  modo          text,
  flow_ns       text,
  texto_p1      text,
  texto_p2      text,
  telefone      text,
  telefone_core text,
  nome          text,
  valor         numeric,
  eh_teste      boolean,
  tentativas    int
)
language sql
security definer
set search_path = public
as $$
  select d.id, d.tipo, d.etapa, cfg.modo, et.flow_ns, et.texto_p1, et.texto_p2,
         coalesce(ev.telefone, c.telefone),
         d.telefone_core,
         coalesce(ev.nome, c.nome),
         coalesce(ev.valor, c.valor),
         exists (select 1 from public.recuperacao_teste_telefones t
                  where t.telefone_core = d.telefone_core),
         d.tentativas
  from public.recuperacao_disparos d
  join public.recuperacao_config  cfg on cfg.tipo = d.tipo
  join public.recuperacao_etapas  et  on et.tipo = d.tipo and et.etapa = d.etapa
  left join public.recovery_events ev on ev.id = d.evento_id
  left join public.compras         c  on c.id  = d.compra_id
  where d.status = 'agendado'
    and d.quando_enviar <= now()
    and d.tentativas < p_max_tentativas
    and cfg.modo <> 'off'
    and et.ativo
  order by d.quando_enviar
  limit p_limite;
$$;
