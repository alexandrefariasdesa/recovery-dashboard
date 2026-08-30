-- =============================================================================
-- 0019_convites_aula_retry_diario.sql — falha de um dia não mata a convidada
--
-- O DEFEITO QUE ISSO CONSERTA: as 4 chamadas do cron de disparo acontecem em
-- 15 minutos (12:00/12:05/12:10/12:15 UTC). Se o ManyChat estiver instável
-- nesses 15 minutos, a linha queima as 4 tentativas, fica em 'erro' — e nunca
-- mais é tentada: `disparar` filtra `tentativas < 4` e a seleção não reinsere
-- (o dedupe por telefone_core é vitalício). Uma oscilação de 15 minutos
-- apagaria a leva inteira do dia, em silêncio e para sempre.
--
-- A CORREÇÃO: a seleção das 08h30 (que roda ANTES do disparo das 09h) devolve
-- as tentativas de quem ficou em 'erro' em dias anteriores. No dia seguinte a
-- pessoa entra na fila de novo — e o convite continua válido, porque a
-- mensagem é "a aula é HOJE", não uma data fixa.
--
-- Dois limites pra isso não virar retentativa eterna:
--   • erro permanente fica de fora: telefone que nem vira WhatsApp (waPhone),
--     'not a valid WhatsApp ID' e 'Subscriber is not active' — os três que a
--     recuperação já mostrou serem definitivos (35+17+3 casos em 4 dias);
--   • só até 3 dias depois da seleção. Passou disso, a linha morre em 'erro'.
-- Idempotente.
-- =============================================================================

create or replace function public.selecionar_convites_aula()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  cfg record;
  n   integer;
  r   integer;
begin
  select * into cfg from public.convites_aula_config where id;
  if cfg is null or not cfg.ativo or cfg.cutoff_compra is null then
    return 0;
  end if;

  -- ── Nova chance pra quem falhou em dias anteriores ────────────────────────
  update public.convites_aula
     set tentativas = 0
   where status = 'erro'
     and tentativas > 0
     and coalesce(erro, '') not ilike '%telefone inv%'
     and coalesce(erro, '') not ilike '%not a valid WhatsApp ID%'
     and coalesce(erro, '') not ilike '%Subscriber is not active%'
     and selecionada_em >= now() - interval '3 days';
  get diagnostics r = row_count;
  if r > 0 then
    raise notice 'convites_aula: % linhas em erro voltaram pra fila', r;
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
