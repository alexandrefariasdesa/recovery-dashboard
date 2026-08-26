-- =============================================================================
-- 0017_aula_clicou_oferta.sql — quem clicou na oferta na sala e não comprou
--
-- É o segmento de maior intenção que a operação tem e que hoje não tem dono:
-- a pessoa estava ao vivo, viu o pitch, clicou no botão da oferta — e não
-- comprou. Ninguém fala com ela depois.
--
-- O motor de recuperação já sabe fazer exatamente isso. Ele não é "o motor do
-- PIX": é uma máquina genérica de (evento) → espera → mensagem → cancela se
-- comprou. O que faltava era o evento. Com o webhook `clicou_oferta` gravando
-- em `aula_eventos` (0015), o evento existe — só falta ele chegar em
-- `recovery_events`, que é onde `agendar_recuperacoes()` procura.
--
-- É isso que o trigger abaixo faz: espelha o clique da sala como um evento de
-- recuperação. Nenhuma linha de código novo na edge function, nenhum cron novo.
--
-- ⚠️ NASCE EM `off`: a mensagem ainda não existe no ManyChat. Ligar exige duas
-- coisas, nesta ordem — criar o fluxo lá e colar o `flow_ns` na etapa, depois
-- virar o modo. Enquanto o flow_ns for null a etapa não dispara nem em
-- 'ligado' (mesma trava do 0006), então não há risco de mandar vazio.
-- =============================================================================

-- ── O tipo no motor ──────────────────────────────────────────────────────────
-- origem 'evento' = nasce de recovery_events (igual pix/carrinho), não de
-- compras. produto_like segue o padrão dos outros tipos de Posições.
insert into public.recuperacao_config (tipo, modo, origem, produto_like, max_por_dia, desde)
values ('clicou_oferta', 'off', 'evento', '%posi%', 500, null)
on conflict (tipo) do nothing;

-- ── A mensagem ───────────────────────────────────────────────────────────────
-- 20 minutos: tempo de a pessoa terminar de assistir e a compra dela cair (a
-- supressão 'ja comprou' roda antes de cada drenagem e tira quem pagou nesse
-- meio tempo). Curto demais e a gente cobra quem está com o checkout aberto;
-- longo demais e a aula já acabou.
insert into public.recuperacao_etapas (tipo, etapa, ordem, atraso, flow_ns, ativo)
values ('clicou_oferta', 'lembrete', 1, interval '20 minutes', null, true)
on conflict (tipo, etapa) do nothing;

-- ── A ponte: clique na sala vira evento de recuperação ───────────────────────
-- Só espelha o que tem telefone: `recovery_events` é cruzado por telefone_core
-- em todo lugar (conversão, supressão, fila), e um evento sem telefone entraria
-- como peça morta que nunca dispara e nunca converte.
--
-- O `raw` guarda a origem pra dar pra auditar depois de onde veio a linha —
-- `recovery_events` passa a ter duas fontes (Payt e webinário) e sem essa marca
-- não dava pra separar.
create or replace function public.espelhar_clique_oferta()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.evento <> 'clicou_oferta' then
    return new;
  end if;
  if coalesce(new.telefone_core, '') = '' then
    return new;
  end if;

  insert into public.recovery_events (evento_em, tipo, nome, telefone, valor, raw)
  values (
    new.evento_em,
    'clicou_oferta',
    new.nome,
    new.telefone,
    new.valor,
    jsonb_build_object('origem', 'webinar-webhook', 'aula_evento_id', new.id)
  );

  return new;
end;
$$;

drop trigger if exists aula_eventos_espelha_clique on public.aula_eventos;
create trigger aula_eventos_espelha_clique
  after insert on public.aula_eventos
  for each row
  execute function public.espelhar_clique_oferta();

comment on function public.espelhar_clique_oferta is
  'Clique na oferta dentro do webinário vira linha em recovery_events, pra o '
  'motor de recuperação atender o segmento sem código novo.';
