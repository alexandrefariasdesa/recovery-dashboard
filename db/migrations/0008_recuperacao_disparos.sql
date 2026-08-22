-- =============================================================================
-- 0008_recuperacao_disparos.sql — recuperação (PIX / boleto / carrinho) saindo
-- do Make, com MODO DE TESTE pra rodar em paralelo sem mandar nada pra ninguém.
--
-- Mesmo maquinário do convite da aula (0006/0007), com uma peça a mais: aqui a
-- hora do disparo é RELATIVA ao evento ("pix gerado → 10 min depois a 1ª"), não
-- um horário do dia. Então existe uma FILA com hora marcada:
--
--   cron 5/5min -> ?fase=agendar  -> varre recovery_events sem escada e cria as
--                                    linhas de `recuperacao_disparos`
--   cron 5/5min -> ?fase=disparar -> drena o que venceu (quando_enviar <= now())
--
-- O agendador varre a tabela de eventos em vez de o webhook empurrar — assim
-- NÃO precisa mexer no payt-webhook (menos risco) e funciona retroativo.
--
-- ── MODO (por tipo de evento, começa tudo em 'off') ──────────────────────────
--   off       nada é agendado
--   simulado  agenda e marca 'simulado' na hora — NÃO chama o ManyChat.
--             É o modo pra rodar junto do Make e comparar sem mandar mensagem.
--   teste     dispara DE VERDADE só pros telefones de `recuperacao_teste_telefones`;
--             todo o resto vira 'simulado'.
--   ligado    dispara pra todo mundo (aí sim o Make sai de cena)
--
-- Trava de segurança: `desde` — nada anterior a essa data é agendado, pra
-- ligar o motor não disparar em cima de 25 mil PIX históricos.
-- Idempotente.
-- =============================================================================

-- ── Config por tipo de evento ────────────────────────────────────────────────
create table if not exists public.recuperacao_config (
  tipo         text primary key,       -- espelha recovery_events.tipo
  modo         text not null default 'off'
               check (modo in ('off', 'simulado', 'teste', 'ligado')),
  desde        timestamptz,            -- não agenda nada anterior a isso
  max_por_dia  int not null default 500
);

insert into public.recuperacao_config (tipo, modo) values
  ('pix_gerado', 'off'),
  ('pix_expirado', 'off'),
  ('boleto_expirado', 'off'),
  ('carrinho_abandonado', 'off')
on conflict (tipo) do nothing;

-- ── Telefones de teste (modo 'teste' só dispara pra estes) ───────────────────
create table if not exists public.recuperacao_teste_telefones (
  telefone_core text primary key,
  nome          text,
  criado_em     timestamptz not null default now()
);

-- ── Escada de mensagens de cada tipo ─────────────────────────────────────────
-- `atraso` é contado a partir do evento. `texto_p1`/`texto_p2` viram o corpo do
-- template aprovado (mesma mecânica do 0007); `{nome}` e `{valor}` são trocados
-- pelos dados do evento. flow_ns null = etapa não dispara.
create table if not exists public.recuperacao_etapas (
  id        bigint generated always as identity primary key,
  tipo      text not null references public.recuperacao_config (tipo) on delete cascade,
  etapa     text not null,
  ordem     int  not null,
  atraso    interval not null,
  template  text,
  flow_ns   text,
  texto_p1  text,
  texto_p2  text,
  ativo     boolean not null default true,
  unique (tipo, etapa)
);

-- Cadência inicial (1 mensagem por tipo, espelhando o que o Make faz hoje).
-- Pra acrescentar repescagem é um insert: (tipo, 'repescagem', 2, '3 hours', ...).
insert into public.recuperacao_etapas (tipo, etapa, ordem, atraso, texto_p1, texto_p2) values
  ('pix_gerado',          'lembrete', 1, '10 minutes',
   'Oi {nome} 💗 vi que seu PIX de R$ {valor} foi gerado e ainda não caiu.',
   'O código expira rápido — quer que eu te mande de novo?'),
  ('pix_expirado',        'lembrete', 1, '5 minutes',
   'Oi {nome} 💗 seu PIX de R$ {valor} expirou antes de cair.',
   'Se ainda quiser, eu gero um novo agora pra você.'),
  ('boleto_expirado',     'lembrete', 1, '5 minutes',
   'Oi {nome} 💗 seu boleto de R$ {valor} venceu sem pagamento.',
   'Quer que eu gere um novo? Ou prefere PIX, que cai na hora?'),
  ('carrinho_abandonado', 'lembrete', 1, '15 minutes',
   'Oi {nome} 💗 vi que você começou e não terminou.',
   'Ficou alguma dúvida? Me conta que eu te ajudo.')
on conflict (tipo, etapa) do nothing;

-- ── Fila de disparos ─────────────────────────────────────────────────────────
create table if not exists public.recuperacao_disparos (
  id               bigint generated always as identity primary key,
  evento_id        bigint not null references public.recovery_events (id) on delete cascade,
  tipo             text   not null,
  etapa            text   not null,
  telefone_core    text   not null,
  quando_enviar    timestamptz not null,
  status           text   not null default 'agendado'
                   check (status in ('agendado', 'enviado', 'simulado', 'cancelado', 'erro')),
  motivo           text,                -- por que foi cancelado (ex.: 'ja comprou')
  tentativas       int    not null default 0,
  erro             text,
  mc_subscriber_id text,
  enviado_em       timestamptz,
  criado_em        timestamptz not null default now(),
  unique (evento_id, etapa)
);
create index if not exists recuperacao_disparos_fila_idx
  on public.recuperacao_disparos (status, quando_enviar);
create index if not exists recuperacao_disparos_tipo_idx
  on public.recuperacao_disparos (tipo, criado_em);

alter table public.recuperacao_config           enable row level security;
alter table public.recuperacao_etapas           enable row level security;
alter table public.recuperacao_disparos         enable row level security;
alter table public.recuperacao_teste_telefones  enable row level security;
-- Sem policy: só o service_role (edge function + dashboard) toca.

-- ── Agendador: cria a escada dos eventos que ainda não têm ───────────────────
create or replace function public.agendar_recuperacoes(p_limite int default 500)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  insert into public.recuperacao_disparos
    (evento_id, tipo, etapa, telefone_core, quando_enviar)
  select ev.id, ev.tipo, et.etapa, ev.telefone_core, ev.evento_em + et.atraso
  from public.recovery_events ev
  join public.recuperacao_config cfg on cfg.tipo = ev.tipo
  join public.recuperacao_etapas et  on et.tipo  = ev.tipo and et.ativo
  where cfg.modo <> 'off'
    and cfg.desde is not null
    and ev.evento_em >= cfg.desde
    and coalesce(ev.telefone_core, '') <> ''
    and not exists (
      select 1 from public.recuperacao_disparos d
      where d.evento_id = ev.id and d.etapa = et.etapa
    )
  order by ev.evento_em
  limit p_limite
  on conflict (evento_id, etapa) do nothing;

  get diagnostics n = row_count;
  return n;
end;
$$;

-- ── Supressão: quem já comprou depois do evento sai da fila ──────────────────
-- Roda antes de cada drenagem. Substitui o Search Rows/comprador-check do Make.
create or replace function public.cancelar_recuperacoes_compradas()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  update public.recuperacao_disparos d
     set status = 'cancelado', motivo = 'ja comprou'
    from public.recovery_events ev
   where ev.id = d.evento_id
     and d.status = 'agendado'
     and exists (
       select 1 from public.compras c
        where c.telefone_core = d.telefone_core
          and c.compra_em >= ev.evento_em
     );
  get diagnostics n = row_count;
  return n;
end;
$$;

-- ── Fila do que já venceu, com tudo que a edge function precisa ──────────────
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
         ev.telefone, d.telefone_core, ev.nome, ev.valor,
         exists (select 1 from public.recuperacao_teste_telefones t
                  where t.telefone_core = d.telefone_core),
         d.tentativas
  from public.recuperacao_disparos d
  join public.recovery_events   ev  on ev.id  = d.evento_id
  join public.recuperacao_config cfg on cfg.tipo = d.tipo
  join public.recuperacao_etapas et  on et.tipo = d.tipo and et.etapa = d.etapa
  where d.status = 'agendado'
    and d.quando_enviar <= now()
    and d.tentativas < p_max_tentativas
    and cfg.modo <> 'off'
    and et.ativo
  order by d.quando_enviar
  limit p_limite;
$$;

-- Guarda o texto exato que foi (ou teria sido) enviado — é o que permite
-- comparar o modo simulado com o que o Make manda hoje.
alter table public.recuperacao_disparos add column if not exists preview text;
comment on column public.recuperacao_disparos.preview is
  'p1 + p2 já renderizados ({nome}/{valor} trocados). Preenchido tanto no envio real quanto no simulado.';
