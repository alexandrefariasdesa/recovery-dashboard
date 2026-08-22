-- =============================================================================
-- 0005_convites_aula.sql — convite pra AULA aos 7 dias de compra (Posições Secretas)
--
-- Estrutura validada em 21/08: Supabase seleciona a base do dia e o controle
-- definitivo; a edge function `aula-convite` dispara via API do ManyChat
-- (SEM Make, SEM planilha). A cadência do dia (13 mensagens) vive num fluxo
-- único do ManyChat com Smart Delays.
--
--   08h30 BRT (pg_cron) -> fase=selecionar -> selecionar_convites_aula()
--   09h00 BRT (pg_cron) -> fase=disparar   -> ManyChat createSubscriber +
--                          link da sala personalizado + sendFlow
--
-- Regra: compradora 'posi%' com >= 7 dias de compra (parede de relógio de
-- São Paulo), a partir de `cutoff_compra`. Dedupe por telefone_core — uma
-- pessoa entra UMA vez na vida, nunca repete.
--
-- Liga/desliga sem redeploy: singleton `convites_aula_config`. GO-LIVE =
--   update convites_aula_config set ativo = true,
--          cutoff_compra = (now() at time zone 'America/Sao_Paulo')::date - 7;
-- (assim a primeira leva é exatamente quem completa 7 dias no dia da largada).
-- Idempotente.
-- =============================================================================

-- E-mail da compradora: o link da sala (Applive) é pré-preenchido com
-- nome+email+telefone. O payt-webhook passa a gravar; retroativo via backfill.
alter table public.compras add column if not exists email text;

-- ── Config (singleton): liga/desliga + largada + trava de volume ─────────────
create table if not exists public.convites_aula_config (
  id            boolean primary key default true check (id),
  ativo         boolean not null default false,
  cutoff_compra date,
  max_por_dia   int not null default 300
);
insert into public.convites_aula_config (id, ativo)
values (true, false)
on conflict (id) do nothing;

-- ── Controle: 1 linha por compradora convidada (nunca repete) ────────────────
create table if not exists public.convites_aula (
  id               bigint generated always as identity primary key,
  telefone_core    text not null unique,
  telefone         text not null,
  nome             text,
  email            text,
  compra_em        timestamptz not null,
  aula_data        date,          -- dia da aula pra qual foi convidada (carimbado no envio)
  link_sala        text,          -- link Applive personalizado enviado
  mc_subscriber_id text,          -- id do subscriber no ManyChat
  status           text not null default 'selecionada',  -- selecionada | enviada | erro
  erro             text,
  tentativas       int not null default 0,
  selecionada_em   timestamptz not null default now(),
  enviada_em       timestamptz
);
create index if not exists convites_aula_status_idx
  on public.convites_aula (status, selecionada_em);

alter table public.convites_aula        enable row level security;
alter table public.convites_aula_config enable row level security;
-- Sem policy: só o service_role (edge function + dashboard) toca.

-- ── Seleção da base do dia ───────────────────────────────────────────────────
-- Elegível: produto 'posi', telefone válido, compra entre cutoff_compra e
-- hoje-7 (BRT), sem linha em convites_aula. Pega a compra MAIS ANTIGA de cada
-- telefone e insere as mais antigas primeiro (fila justa), até max_por_dia.
create or replace function public.selecionar_convites_aula()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  cfg record;
  n   integer;
begin
  select * into cfg from public.convites_aula_config where id;
  if cfg is null or not cfg.ativo or cfg.cutoff_compra is null then
    return 0;
  end if;

  insert into public.convites_aula (telefone_core, telefone, nome, email, compra_em)
  select s.telefone_core, s.telefone, s.nome, s.email, s.compra_em
  from (
    select distinct on (c.telefone_core)
           c.telefone_core, c.telefone, c.nome, c.email, c.compra_em
    from public.compras c
    where c.produto ilike '%posi%'
      and coalesce(c.telefone_core, '') <> ''
      and (c.compra_em at time zone 'America/Sao_Paulo')::date >= cfg.cutoff_compra
      and (c.compra_em at time zone 'America/Sao_Paulo')::date
            <= (now() at time zone 'America/Sao_Paulo')::date - 7
      and not exists (
        select 1 from public.convites_aula ca
        where ca.telefone_core = c.telefone_core
      )
    order by c.telefone_core, c.compra_em asc
  ) s
  order by s.compra_em asc
  limit cfg.max_por_dia
  on conflict (telefone_core) do nothing;

  get diagnostics n = row_count;
  return n;
end;
$$;
