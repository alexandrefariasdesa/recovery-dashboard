-- 0020_compras_utm.sql
-- =============================================================================
-- UTM da compra: de onde a venda veio.
--
-- Motivo: o fluxo de boas-vindas do Instagram não pede contato, então a pessoa
-- que compra depois dele não casa por telefone com `manychat_eventos` (na
-- varredura de 30/08/2026: 1 pessoa com telefone em 93.606). A Payt manda os
-- parâmetros de UTM da origem no payload do webhook — é essa a chave que liga a
-- venda ao fluxo, sem precisar de identidade da pessoa.
--
-- Duas colunas, com papéis diferentes:
--   utm  — o conjunto de parâmetros como veio, para não perder nada que a Payt
--          mande hoje ou passe a mandar depois (source, medium, campaign,
--          content, term, src, sck…).
--   raw  — o payload inteiro da compra aprovada. Já existia na tabela e só era
--          preenchida pela rota /compra do ManyChat; passa a valer para a Payt
--          também, para que um UTM com nome inesperado possa ser recuperado por
--          backfill em vez de exigir um novo deploy do webhook.
--
-- Índices em source/campaign porque é por eles que o painel filtra.
-- =============================================================================

alter table public.compras
  add column if not exists utm jsonb;

create index if not exists compras_utm_source_idx
  on public.compras ((utm ->> 'utm_source'));

create index if not exists compras_utm_campaign_idx
  on public.compras ((utm ->> 'utm_campaign'));

comment on column public.compras.utm is
  'Parâmetros de origem da venda como vieram no webhook da Payt (utm_source, utm_medium, utm_campaign, utm_content, utm_term, src, sck). Chave de atribuição quando não existe identidade da pessoa — ver 0020.';
