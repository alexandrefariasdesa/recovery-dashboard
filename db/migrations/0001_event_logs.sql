-- =============================================================================
-- 0001_event_logs.sql — camada de dados nova do recovery_dashboard (Fase 1)
--
-- Migra do Google Sheets para Postgres SÓ o "Papel A": os LOGS DE EVENTO de alto
-- volume, append-only, que ninguém lê de volta a não ser o dashboard. É o que
-- estoura a cota de escrita do Sheets (o 429/retry dos Workers) e queima
-- operação do Make por evento.
--
-- FICAM NO SHEETS (por enquanto — "Papel B", baixo volume, lidos por automação):
--   - Leads/compras com as colunas de controle (elegivel_2a_chamada,
--     aula_chamada_em, entrou_no_grupo) — o Make lê/escreve.
--   - Disparo 2a Chamada / Disparo Aula / ja_disparado — o Make lê.
-- Esses são gerados a partir do Postgres numa fase depois, sem tocar no Make.
--
-- Formas espelham exatamente o que os Workers/Make gravam hoje:
--   recuperacoes      (Make):  evento_em, tipo, nome, telefone, valor
--   eventos_manychat  (Worker): ts, telefone, subscriber_id, fluxo, etapa
--   cliques_manychat  (Worker): clicado_em, telefone, subscriber_id, tipo, url
--
-- Telefone: guardamos o valor cru E uma coluna só-dígitos gerada, indexada, pro
-- cruzamento por telefone (a lógica de variante com/sem 9 do BR fica no read).
-- =============================================================================

-- Só-dígitos de um telefone, imutável (pra usar em coluna gerada + índice).
create or replace function public.only_digits(p text)
returns text
language sql
immutable
as $$ select regexp_replace(coalesce(p,''), '\D', '', 'g'); $$;

-- ---------------------------------------------------------------------------
-- recovery_events  (aba `recuperacoes`)
-- tipo ∈ pix_gerado|pix_expirado|boleto_gerado|boleto_expirado|
--        carrinho_abandonado|pix_boleto_gerado|pix_boleto_expirado
-- ---------------------------------------------------------------------------
create table if not exists public.recovery_events (
  id             bigint generated always as identity primary key,
  evento_em      timestamptz not null,
  tipo           text        not null,
  nome           text,
  telefone       text,
  telefone_norm  text generated always as (public.only_digits(telefone)) stored,
  valor          numeric(12,2),
  ingested_at    timestamptz not null default now()
);
create index if not exists recovery_events_evento_em_idx on public.recovery_events (evento_em);
create index if not exists recovery_events_tel_idx       on public.recovery_events (telefone_norm);
create index if not exists recovery_events_tipo_idx      on public.recovery_events (tipo);

-- ---------------------------------------------------------------------------
-- manychat_eventos  (aba `eventos_manychat`) — funil recebeu→entrou→engajou
-- ---------------------------------------------------------------------------
create table if not exists public.manychat_eventos (
  id             bigint generated always as identity primary key,
  evento_em      timestamptz not null,
  telefone       text,
  telefone_norm  text generated always as (public.only_digits(telefone)) stored,
  subscriber_id  text,
  fluxo          text        not null,
  etapa          text        not null,   -- recebeu | entrou | engajou
  ingested_at    timestamptz not null default now()
);
create index if not exists manychat_eventos_em_idx    on public.manychat_eventos (evento_em);
create index if not exists manychat_eventos_fluxo_idx on public.manychat_eventos (fluxo, etapa);
create index if not exists manychat_eventos_tel_idx   on public.manychat_eventos (telefone_norm);

-- ---------------------------------------------------------------------------
-- manychat_cliques  (aba `cliques_manychat`)
-- ---------------------------------------------------------------------------
create table if not exists public.manychat_cliques (
  id             bigint generated always as identity primary key,
  clicado_em     timestamptz not null,
  telefone       text,
  telefone_norm  text generated always as (public.only_digits(telefone)) stored,
  subscriber_id  text,
  tipo           text,
  url            text,
  ingested_at    timestamptz not null default now()
);
create index if not exists manychat_cliques_em_idx  on public.manychat_cliques (clicado_em);
create index if not exists manychat_cliques_tel_idx on public.manychat_cliques (telefone_norm);

-- ---------------------------------------------------------------------------
-- RLS: ninguém acessa pela anon/authenticated key. Só o service_role (Workers
-- de ingestão e o dashboard) toca aqui, e ele ignora RLS. Ligamos RLS sem
-- policy pra fechar por padrão — nada de leitura pública de dados de cliente.
-- ---------------------------------------------------------------------------
alter table public.recovery_events   enable row level security;
alter table public.manychat_eventos  enable row level security;
alter table public.manychat_cliques  enable row level security;
