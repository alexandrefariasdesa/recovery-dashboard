-- =============================================================================
-- 0015_aula_eventos.sql — o que acontece DENTRO do webinário
--
-- POR QUE GENÉRICO: hoje o loop da aula é aberto. `convites_aula_envios` sabe o
-- que a gente MANDOU; ninguém sabe se a pessoa entrou, quanto ficou, se clicou
-- na oferta. A plataforma (Applive) expõe uma lista de webhooks e a decisão foi
-- cadastrar TODOS — então esta tabela não modela um evento específico: ela
-- aceita qualquer um, guarda o payload inteiro em `raw`, e deixa o dashboard
-- descobrir sozinho os nomes que chegaram.
--
-- É o mesmo espírito do payt-webhook ("logamos o corpo inteiro e mapeamos por
-- caminhos plausíveis"), levado um passo adiante: aqui nem o conjunto de tipos
-- é conhecido de antemão, então NADA é rejeitado por não ser reconhecido. Um
-- evento novo aparece no painel como uma linha nova, não como um erro.
--
-- Quando os nomes reais estiverem à vista (uma aula basta), aí sim vale fixar
-- os que interessam: 'entrou na sala' vira supressão das mensagens das 19h15 e
-- 19h30, e 'clicou na oferta' vira um tipo em recuperacao_config.
-- =============================================================================

create table if not exists public.aula_eventos (
  id            bigint generated always as identity primary key,

  evento_em     timestamptz not null,        -- quando aconteceu (do payload, ou a chegada)
  evento        text not null,               -- nome canônico: minúsculo, sem acento, com _
  evento_raw    text,                        -- o nome exato como a plataforma escreveu

  -- Identificação. A chave de junção do sistema é telefone_core (mesma de
  -- compras/recovery_events/convites_aula). O e-mail entra como segunda via:
  -- num webinário é comum o evento sair só com e-mail, e sem uma das duas
  -- chaves o evento chega e não encaixa em ninguém.
  telefone      text,
  telefone_core text generated always as (public.phone_core(telefone)) stored,
  email         text,
  nome          text,

  -- Campos que quase toda plataforma manda de alguma forma. Nulos quando o
  -- evento não tem — não é erro, é a natureza de um receptor que aceita tudo.
  aula_data     date,          -- dia da sessão
  sala          text,          -- id/nome do webinário ou da sessão
  duracao_seg   int,           -- permanência, quando o evento carrega
  url           text,          -- destino do clique, quando for um clique
  valor         numeric(12,2), -- quando o evento for de compra dentro da sala

  raw           jsonb not null,              -- o payload inteiro, sempre
  ingested_at   timestamptz not null default now(),

  -- Reenvio não duplica. Plataforma de webinário reenvia com frequência (e a
  -- gente responde 200 mesmo no que não entende, o que aumenta o reenvio).
  dedupe_key    text unique
);

create index if not exists aula_eventos_evento_idx on public.aula_eventos (evento, evento_em desc);
create index if not exists aula_eventos_core_idx   on public.aula_eventos (telefone_core);
create index if not exists aula_eventos_email_idx  on public.aula_eventos (lower(email));
create index if not exists aula_eventos_em_idx     on public.aula_eventos (evento_em desc);

comment on table public.aula_eventos is
  'Eventos crus da plataforma de webinário. Aceita QUALQUER tipo — os nomes são '
  'descobertos pelo painel, não declarados aqui.';

-- ── Catálogo: o que efetivamente chegou ──────────────────────────────────────
-- É a peça que substitui a lista que a gente não tem. Em vez de manter um
-- enum à mão, o painel pergunta pro banco quais eventos existem, com que
-- volume, e QUANTO deles vem identificável — porque um evento que chega sem
-- telefone e sem e-mail é bonito no gráfico e inútil na operação.
create or replace view public.v_aula_eventos_catalogo as
select
  evento,
  min(evento_raw)                                                as exemplo_nome,
  count(*)                                                       as total,
  count(*) filter (where evento_em >= now() - interval '7 days') as d7,
  min(evento_em)                                                 as primeiro,
  max(evento_em)                                                 as ultimo,
  count(*) filter (where coalesce(telefone_core, '') <> '')      as com_telefone,
  count(*) filter (where coalesce(email, '') <> '')              as com_email,
  count(*) filter (where coalesce(telefone_core, '') = ''
                     and coalesce(email, '') = '')               as sem_chave,
  count(distinct coalesce(nullif(telefone_core, ''), lower(email))) as pessoas
from public.aula_eventos
group by evento;

comment on view public.v_aula_eventos_catalogo is
  'Auto-descoberta: quais webhooks a plataforma está de fato mandando, e quantos '
  'deles dá pra cruzar com uma pessoa.';

-- ── O evento cruzado com quem foi convidada ──────────────────────────────────
-- Fecha o loop que hoje não existe: a linha de `convites_aula` diz que mandamos,
-- esta view diz o que a pessoa fez. Left join no convite (nem todo mundo na sala
-- veio do nosso convite — tem tráfego direto), e a junção tenta telefone e cai
-- pro e-mail, que é a razão de guardar os dois.
create or replace view public.v_aula_eventos_pessoa as
select
  e.id, e.evento_em, e.evento, e.aula_data, e.sala, e.duracao_seg, e.url, e.valor,
  coalesce(nullif(e.telefone_core, ''), lower(e.email)) as chave,
  coalesce(e.nome, cv.nome)                             as nome,
  coalesce(nullif(e.telefone_core, ''), cv.telefone_core) as telefone_core,
  e.email,
  (cv.id is not null)                                   as veio_do_convite,
  cv.enviada_em                                         as convite_enviado_em
from public.aula_eventos e
left join public.convites_aula cv
       on (nullif(e.telefone_core, '') is not null and cv.telefone_core = e.telefone_core)
       or (nullif(e.email, '') is not null and lower(cv.email) = lower(e.email));
