-- =============================================================================
-- 0018_optout.sql — lista de bloqueio (opt-out) do disparo por API
--
-- Nasce de um pedido simples: um bloco no ManyChat que, ao ser tocado, joga a
-- pessoa numa base e ela PARA de receber mensagem disparada por API — e outro
-- bloco que desfaz. O ManyChat sozinho não resolve isso, porque quem manda a
-- mensagem aqui não é um fluxo dele: é a edge function `recuperacao-disparo`
-- (e a `aula-convite`) chamando sendFlow de fora. Custom field do contato não
-- é consultado por elas. Então o "não me mande mais nada" precisa morar no
-- banco, num lugar que TODO caminho de saída olhe antes de enviar.
--
--   ManyChat (bloco BLOQUEAR)    -> edge function `optout?acao=bloquear`
--   ManyChat (bloco DESBLOQUEAR) -> edge function `optout?acao=desbloquear`
--                                    v
--                             public.optout  (a base)
--                                    v
--   fila_recuperacao / fila_convites_etapa / selecionar_convites_aula
--   filtram quem está bloqueado — nada sai por API pra essas pessoas.
--
-- A chave é `telefone_core` (0003), a mesma que colapsa com/sem o 9. Bloquear
-- pelo telefone e não pelo subscriber_id é de propósito: a pessoa continua
-- bloqueada mesmo se o contato do ManyChat for apagado e recriado depois.
--
-- Desbloquear NÃO apaga a linha — vira `bloqueado = false`, com a data. A
-- tabela é também o registro de quem pediu pra sair, que é o que interessa se
-- alguém reclamar de ter recebido mensagem depois de bloquear.
-- Idempotente.
-- =============================================================================

-- ── A base ───────────────────────────────────────────────────────────────────
create table if not exists public.optout (
  telefone_core    text primary key,
  telefone         text,                 -- último formato bruto visto
  nome             text,
  mc_subscriber_id text,
  bloqueado        boolean not null default true,
  origem           text,                 -- de onde veio a última ação (ex.: 'manychat:recuperacao_pix')
  motivo           text,
  bloqueado_em     timestamptz,
  desbloqueado_em  timestamptz,
  atualizado_em    timestamptz not null default now()
);

-- Índice parcial: as filas só perguntam pelos bloqueados.
create index if not exists optout_bloqueado_idx
  on public.optout (telefone_core) where bloqueado;

-- Histórico: cada toque nos blocos vira uma linha, inclusive o toque repetido
-- (`efetivo = false`), que é como se enxerga alguém apertando BLOQUEAR duas
-- vezes ou indo e voltando.
create table if not exists public.optout_log (
  id               bigint generated always as identity primary key,
  telefone_core    text not null,
  acao             text not null check (acao in ('bloquear', 'desbloquear')),
  efetivo          boolean not null,     -- false = já estava nesse estado
  origem           text,
  motivo           text,
  mc_subscriber_id text,
  criado_em        timestamptz not null default now()
);
create index if not exists optout_log_tel_idx
  on public.optout_log (telefone_core, criado_em desc);

alter table public.optout     enable row level security;
alter table public.optout_log enable row level security;
-- Sem policy: só o service_role (edge functions + painel) toca.

-- ── Ler ──────────────────────────────────────────────────────────────────────
create or replace function public.optout_bloqueado(p_telefone text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.optout o
     where o.telefone_core = public.phone_core(p_telefone) and o.bloqueado
  );
$$;

-- ── Bloquear ─────────────────────────────────────────────────────────────────
-- Devolve jsonb pra edge function repassar direto pro ManyChat (Response
-- Mapping). `ja_estava` distingue o clique novo do clique repetido.
create or replace function public.optout_bloquear(
  p_telefone         text,
  p_origem           text default null,
  p_motivo           text default null,
  p_nome             text default null,
  p_mc_subscriber_id text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  core text;
  ja   boolean;
begin
  core := public.phone_core(p_telefone);
  if coalesce(core, '') = '' then
    return jsonb_build_object('ok', false, 'erro', 'telefone invalido');
  end if;

  select o.bloqueado into ja from public.optout o where o.telefone_core = core;

  insert into public.optout as o
    (telefone_core, telefone, nome, mc_subscriber_id, bloqueado, origem, motivo, bloqueado_em)
  values
    (core, nullif(p_telefone, ''), nullif(p_nome, ''), nullif(p_mc_subscriber_id, ''),
     true, nullif(p_origem, ''), nullif(p_motivo, ''), now())
  on conflict (telefone_core) do update
     set bloqueado        = true,
         telefone         = coalesce(excluded.telefone, o.telefone),
         nome             = coalesce(excluded.nome, o.nome),
         mc_subscriber_id = coalesce(excluded.mc_subscriber_id, o.mc_subscriber_id),
         origem           = coalesce(excluded.origem, o.origem),
         motivo           = coalesce(excluded.motivo, o.motivo),
         -- quem já estava bloqueado mantém a data original do pedido
         bloqueado_em     = case when o.bloqueado then o.bloqueado_em else now() end,
         atualizado_em    = now();

  insert into public.optout_log (telefone_core, acao, efetivo, origem, motivo, mc_subscriber_id)
  values (core, 'bloquear', coalesce(ja, false) = false,
          nullif(p_origem, ''), nullif(p_motivo, ''), nullif(p_mc_subscriber_id, ''));

  return jsonb_build_object(
    'ok', true, 'telefone_core', core, 'bloqueado', true, 'ja_estava', coalesce(ja, false)
  );
end;
$$;

-- ── Desbloquear ──────────────────────────────────────────────────────────────
-- Não apaga: guarda que houve bloqueio e quando saiu dele.
create or replace function public.optout_desbloquear(
  p_telefone         text,
  p_origem           text default null,
  p_motivo           text default null,
  p_mc_subscriber_id text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  core text;
  ja   boolean;
begin
  core := public.phone_core(p_telefone);
  if coalesce(core, '') = '' then
    return jsonb_build_object('ok', false, 'erro', 'telefone invalido');
  end if;

  select o.bloqueado into ja from public.optout o where o.telefone_core = core;

  update public.optout o
     set bloqueado        = false,
         desbloqueado_em  = now(),
         origem           = coalesce(nullif(p_origem, ''), o.origem),
         motivo           = coalesce(nullif(p_motivo, ''), o.motivo),
         mc_subscriber_id = coalesce(nullif(p_mc_subscriber_id, ''), o.mc_subscriber_id),
         atualizado_em    = now()
   where o.telefone_core = core;

  insert into public.optout_log (telefone_core, acao, efetivo, origem, motivo, mc_subscriber_id)
  values (core, 'desbloquear', coalesce(ja, false) = true,
          nullif(p_origem, ''), nullif(p_motivo, ''), nullif(p_mc_subscriber_id, ''));

  return jsonb_build_object(
    'ok', true, 'telefone_core', core, 'bloqueado', false,
    'ja_estava', coalesce(ja, false) = false
  );
end;
$$;

-- ── Supressão na recuperação ─────────────────────────────────────────────────
-- Mesma forma de cancelar_recuperacoes_compradas() (0008/0010): roda antes de
-- cada drenagem e deixa a linha visível no painel como cancelada, com motivo —
-- em vez de a pessoa simplesmente sumir da fila sem explicação.
create or replace function public.cancelar_recuperacoes_bloqueadas()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  update public.recuperacao_disparos d
     set status = 'cancelado', motivo = 'bloqueou'
   where d.status = 'agendado'
     and exists (
       select 1 from public.optout o
        where o.telefone_core = d.telefone_core and o.bloqueado
     );
  get diagnostics n = row_count;
  return n;
end;
$$;

-- Cinto e suspensório (mesmo raciocínio do 0016): a marcação acima já tira a
-- pessoa da fila, mas o NOT EXISTS aqui cobre a janela entre cancelar e ler —
-- que é justamente quando alguém aperta BLOQUEAR no meio de um disparo.
-- Corpo idêntico ao do 0009, com o filtro a mais.
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
    and not exists (
      select 1 from public.optout o
       where o.telefone_core = d.telefone_core and o.bloqueado
    )
  order by d.quando_enviar
  limit p_limite;
$$;

-- ── Supressão no convite da aula ─────────────────────────────────────────────
-- Duas portas: quem já está bloqueado nem entra na base do dia, e quem bloqueia
-- depois de entrar para de receber as etapas seguintes (falta_1h / ao_vivo /
-- comecamos). Corpos idênticos aos do 0005 e do 0016, com o filtro a mais.
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
      and not exists (
        select 1 from public.optout o
        where o.telefone_core = c.telefone_core and o.bloqueado
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

create or replace function public.fila_convites_etapa(
  p_etapa           text,
  p_limite          int default 80,
  p_max_tentativas  int default 4
)
returns table (convite_id bigint, mc_subscriber_id text, link_sala text, tentativas int)
language sql
security definer
set search_path = public
as $$
  select ca.id, ca.mc_subscriber_id, ca.link_sala, coalesce(e.tentativas, 0)
  from public.convites_aula ca
  left join public.convites_aula_envios e
         on e.convite_id = ca.id
        and e.etapa      = p_etapa
        and e.aula_data  = (now() at time zone 'America/Sao_Paulo')::date
  where ca.status = 'enviada'
    and ca.mc_subscriber_id is not null
    and ca.aula_data = (now() at time zone 'America/Sao_Paulo')::date
    and (e.id is null or (e.status = 'erro' and e.tentativas < p_max_tentativas))
    and not exists (
      select 1 from public.optout o
       where o.telefone_core = ca.telefone_core and o.bloqueado
    )
    and not (
      exists (select 1 from public.convites_aula_etapas et
                where et.etapa = p_etapa and et.pular_se_entrou)
      and exists (
        select 1 from public.v_aula_entrou_hoje x
         where (x.telefone_core is not null and x.telefone_core = ca.telefone_core)
            or (x.email is not null and x.email = lower(ca.email))
      )
    )
  order by ca.id
  limit p_limite;
$$;

-- ── Visão pro painel ─────────────────────────────────────────────────────────
create or replace view public.v_optout as
  select o.telefone_core, o.telefone, o.nome, o.origem, o.motivo,
         o.bloqueado_em, o.desbloqueado_em, o.atualizado_em
  from public.optout o
  where o.bloqueado;

comment on table public.optout is
  'Quem pediu pra nao receber mais disparo por API. Alimentada pelos blocos '
  'BLOQUEAR/DESBLOQUEAR do ManyChat via edge function `optout`. Consultada por '
  'fila_recuperacao, fila_convites_etapa e selecionar_convites_aula.';
