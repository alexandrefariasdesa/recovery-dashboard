-- =============================================================================
-- 0006_convites_aula_etapas.sql — cadência da aula por FORA do ManyChat
--
-- Muda de arquitetura em relação ao 0005: a cadência do dia NÃO vive mais num
-- fluxo único do ManyChat com Smart Delays (delay é sempre relativo a quando a
-- pessoa entrou no passo — "17h30" virava "150 min depois do clique"). Agora
-- são 4 mensagens, cada uma num fluxo pequeno do ManyChat, disparadas pelo
-- pg_cron na hora cravada:
--
--   09h00 BRT  e_hoje     -> "é hoje" (template com os botões do convite)
--   18h30 BRT  falta_1h   -> "falta 1 hora"
--   19h15 BRT  ao_vivo    -> "abriu a sala, tô ao vivo"
--   19h30 BRT  comecamos  -> "começamos agora"
--
-- Hora e fluxo são DADO, não código: pra mudar o horário é um update aqui +
-- o cron correspondente (db/ops_convite_cron.sql); pra trocar a mensagem é só
-- apontar o `flow_ns` pro fluxo novo.
--
-- Quem recebe as etapas 2-4: quem recebeu o convite HOJE (convites_aula com
-- aula_data = hoje e status 'enviada'). Quem tocou BLOQUEAR é barrado dentro
-- do próprio fluxo do ManyChat (condição clicou_aula = 'bloqueou' na entrada),
-- que é onde esse campo vive. Idempotente.
-- =============================================================================

-- ── Catálogo das etapas (hora + fluxo do ManyChat) ───────────────────────────
create table if not exists public.convites_aula_etapas (
  etapa      text primary key,           -- e_hoje | falta_1h | ao_vivo | comecamos
  ordem      int  not null,
  hora_brt   time not null,              -- documental: quem dispara é o pg_cron
  descricao  text,
  flow_ns    text,                       -- ns do fluxo no ManyChat (null = não dispara)
  ativo      boolean not null default true
);

insert into public.convites_aula_etapas (etapa, ordem, hora_brt, descricao, ativo) values
  ('e_hoje',    1, '09:00', 'É hoje — template do convite, com os botões',  true),
  ('falta_1h',  2, '18:30', 'Falta 1 hora',                                  true),
  ('ao_vivo',   3, '19:15', 'Abriu a sala — tô ao vivo, entra',              true),
  ('comecamos', 4, '19:30', 'Começamos agora',                               true)
on conflict (etapa) do nothing;

-- ── Controle: 1 linha por (convidada, etapa, dia da aula) ────────────────────
create table if not exists public.convites_aula_envios (
  id          bigint generated always as identity primary key,
  convite_id  bigint not null references public.convites_aula (id) on delete cascade,
  etapa       text   not null references public.convites_aula_etapas (etapa),
  aula_data   date   not null,
  status      text   not null default 'enviada',   -- enviada | erro
  tentativas  int    not null default 0,
  erro        text,
  enviada_em  timestamptz,
  criada_em   timestamptz not null default now(),
  unique (convite_id, etapa, aula_data)
);
create index if not exists convites_aula_envios_etapa_idx
  on public.convites_aula_envios (etapa, aula_data, status);

alter table public.convites_aula_envios enable row level security;
alter table public.convites_aula_etapas enable row level security;
-- Sem policy: só o service_role (edge function + dashboard) toca.

-- ── Fila de uma etapa: quem recebeu o convite hoje e ainda não recebeu ela ────
-- Reprocessa 'erro' enquanto tentativas < p_max_tentativas; 'enviada' nunca
-- repete (a unique key + este filtro garantem que ninguém leva a mesma
-- mensagem duas vezes, mesmo com o cron chamando várias vezes seguidas).
create or replace function public.fila_convites_etapa(
  p_etapa           text,
  p_limite          int default 80,
  p_max_tentativas  int default 4
)
returns table (convite_id bigint, mc_subscriber_id text, tentativas int)
language sql
security definer
set search_path = public
as $$
  select ca.id, ca.mc_subscriber_id, coalesce(e.tentativas, 0)
  from public.convites_aula ca
  left join public.convites_aula_envios e
         on e.convite_id = ca.id
        and e.etapa      = p_etapa
        and e.aula_data  = (now() at time zone 'America/Sao_Paulo')::date
  where ca.status = 'enviada'
    and ca.mc_subscriber_id is not null
    and ca.aula_data = (now() at time zone 'America/Sao_Paulo')::date
    and (e.id is null or (e.status = 'erro' and e.tentativas < p_max_tentativas))
  order by ca.id
  limit p_limite;
$$;
