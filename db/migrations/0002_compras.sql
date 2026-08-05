-- =============================================================================
-- 0002_compras.sql — compras aprovadas (o lado da CONVERSÃO)
--
-- Espelha os FATOS da compra (nome, telefone, valor, data, produto) que hoje
-- vão pra planilha de compras/Leads. É o que o dashboard cruza com
-- recovery_events pra marcar quem converteu. Com os dois no Postgres, a
-- conversão vira um JOIN por telefone.
--
-- IMPORTANTE: as colunas de CONTROLE do Papel B (elegivel_2a_chamada,
-- aula_chamada_em, entrou_no_grupo) continuam na planilha Leads — o Make
-- lê/escreve lá. Aqui é só o fato da compra.
--
-- Dedup por transaction_id: reenvio da Payt não duplica a compra (o que
-- inflaria a taxa de conversão). only_digits já existe (0001).
-- Idempotente.
-- =============================================================================

create table if not exists public.compras (
  id             bigint generated always as identity primary key,
  compra_em      timestamptz not null,
  nome           text,
  telefone       text,
  telefone_norm  text generated always as (public.only_digits(telefone)) stored,
  valor          numeric(12,2),
  produto        text,
  transaction_id text,
  raw            jsonb,
  ingested_at    timestamptz not null default now()
);

create index if not exists compras_compra_em_idx on public.compras (compra_em);
create index if not exists compras_tel_idx        on public.compras (telefone_norm);
-- Uma compra por transação. Índice único NÃO-parcial: o Postgres trata NULLs
-- como distintos (várias linhas sem transaction_id convivem), e o upsert
-- ON CONFLICT (transaction_id) precisa de um índice não-parcial pra casar —
-- um índice parcial dá "no unique constraint matching the ON CONFLICT".
create unique index if not exists compras_txn_uidx
  on public.compras (transaction_id);

alter table public.compras enable row level security;
-- Sem policy: só o service_role (webhook + dashboard) toca.

-- recovery_events volta a ter a coluna raw (auto-diagnóstico de tipo não
-- resolvido). Só é preenchida nesses casos raros — não incha o volume normal.
alter table public.recovery_events add column if not exists raw jsonb;
