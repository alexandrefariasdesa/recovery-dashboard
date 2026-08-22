-- =============================================================================
-- 0013_grupo_ids.sql — o id da campanha e do grupo, além do nome
--
-- O payload real do SendFlow (visto em 22/08) manda os dois: `campaignId` +
-- `campaignName`, `groupId`/`groupJid` + `groupName`. Nome de campanha e de
-- grupo são editáveis — guardar só o nome faz o histórico se reescrever quando
-- alguém renomeia. O id é o que amarra.
-- Idempotente.
-- =============================================================================

alter table public.grupo_entradas add column if not exists campanha_id text;
alter table public.grupo_entradas add column if not exists grupo_id     text;

create index if not exists grupo_entradas_campanha_id_idx
  on public.grupo_entradas (campanha_id);

-- Com o id disponível, o dedupe deixa de depender do NOME do grupo: renomear
-- "Grupo de Natal #1" faria a mesma pessoa entrar de novo pela chave antiga,
-- inflando a taxa.
--
-- A chave é uma COLUNA GERADA, não um índice por expressão, porque quem insere
-- é o PostgREST: o `on_conflict=` dele nomeia colunas, e um índice sobre
-- `coalesce(...)` não casa com nenhuma lista de nomes — o insert morreria com
-- "no unique or exclusion constraint matching the ON CONFLICT specification".
alter table public.grupo_entradas
  add column if not exists grupo_chave text
  generated always as (coalesce(grupo_id, grupo, '')) stored;

drop index if exists public.grupo_entradas_uidx;
create unique index if not exists grupo_entradas_uidx
  on public.grupo_entradas (telefone_core, grupo_chave, evento);
