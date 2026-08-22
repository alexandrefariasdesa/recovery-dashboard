-- =============================================================================
-- 0011_grupo_entradas.sql — quem entra nos grupos de WhatsApp, por campanha
--
-- Hoje esse fato mora só na planilha "[LEADS] ENTRADA NOS GRUPOS", escrita pelo
-- Make a partir do webhook do SendFlow. A planilha não tem cabeçalho e parou de
-- receber em 15/07/2026 — ou seja, a entrada em grupo virou um dado morto, e
-- não dá pra responder "qual campanha enche o grupo" com ele.
--
-- Aqui o mesmo evento vira tabela, com a campanha ao lado do telefone, que é a
-- chave que cruza com `compras` e `recovery_events` (mesmo `phone_core` do
-- resto do banco — a variante com/sem o 9 colapsa sozinha).
--
-- `raw` guarda o payload inteiro SEMPRE, não só em caso de erro: o formato de
-- quem vai postar aqui ainda não foi visto de perto, e um campo que a gente não
-- mapeou hoje não pode se perder. Quando o formato estiver claro, o mapeamento
-- melhora sem precisar de backfill.
-- Idempotente.
-- =============================================================================

create table if not exists public.grupo_entradas (
  id             bigint generated always as identity primary key,
  entrou_em      timestamptz not null,
  evento         text,          -- ex: group.updated.members.added
  conta          text,          -- id da conta/instância que reportou
  campanha       text,
  grupo          text,
  telefone       text,
  telefone_norm  text generated always as (public.only_digits(telefone)) stored,
  telefone_core  text generated always as (public.phone_core(telefone)) stored,
  raw            jsonb,
  ingested_at    timestamptz not null default now()
);

create index if not exists grupo_entradas_em_idx       on public.grupo_entradas (entrou_em);
create index if not exists grupo_entradas_core_idx     on public.grupo_entradas (telefone_core);
create index if not exists grupo_entradas_campanha_idx on public.grupo_entradas (campanha);

-- Uma entrada por (pessoa, grupo, evento): o webhook reenviado não vira duas
-- entradas, o que inflaria "quantas pessoas a campanha colocou no grupo".
-- Sair e voltar no mesmo grupo também conta uma vez — é o que interessa aqui.
create unique index if not exists grupo_entradas_uidx
  on public.grupo_entradas (telefone_core, grupo, evento);

alter table public.grupo_entradas enable row level security;
-- Sem policy: só o service_role (worker + painel) toca.
