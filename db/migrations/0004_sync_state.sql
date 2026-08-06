-- =============================================================================
-- 0004_sync_state.sql — cursor do sync incremental Sheets→Postgres
--
-- As abas `eventos_manychat` e `cliques_manychat` são append-only (os Cloudflare
-- Workers só acrescentam linhas), e os eventos NOVOS ainda vão só pro Sheets.
-- O sync (db/sync_manychat.py) lê a planilha e insere no Postgres só as linhas
-- além do cursor. Como a planilha só cresce (nunca reordena/apaga), o cursor por
-- ÍNDICE DE LINHA é à prova de duplicata.
--
-- last_row = quantas linhas de DADOS já foram sincronizadas daquela aba.
-- =============================================================================
create table if not exists public.sync_state (
  source     text primary key,
  last_row   int  not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.sync_state enable row level security;  -- só service_role toca
