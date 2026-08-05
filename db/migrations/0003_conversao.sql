-- =============================================================================
-- 0003_conversao.sql — a análise "quem comprou pós-recuperação" NO BANCO
--
-- Reproduz em SQL o que processors/recovery.py faz em Python:
--   - casa telefone com a VARIANTE do 9 do celular BR (phone_variants);
--   - pega a compra MAIS RECENTE daquele telefone;
--   - se compra.data >= evento.data (comparação por DIA), converteu = true;
--   - valor_recuperado = valor da COMPRA (não do evento).
--
-- A comparação de data é feita no fuso de São Paulo (mesma parede de relógio da
-- planilha), pra bater com o dashboard.
-- =============================================================================

-- phone_core: chave canônica que colapsa a variante com/sem o 9. Espelha
-- utils.normalize_phone + phone_variants: tira o 55, e reduz o celular de 11
-- dígitos (DDD+9+8) pro formato de 10 (DDD+8). Assim "92994305962" e
-- "9294305962" viram a MESMA chave. IMMUTABLE pra poder ser coluna gerada.
create or replace function public.phone_core(p text)
returns text
language sql
immutable
as $$
  with a as (select public.only_digits(p) as d0),
       b as (select case when length(d0) >= 12 and left(d0,2) = '55'
                         then substr(d0,3) else d0 end as d from a)
  select case when length(d) = 11 and substr(d,3,1) = '9'
              then substr(d,1,2) || substr(d,4)
              else d end
  from b;
$$;

alter table public.recovery_events
  add column if not exists telefone_core text generated always as (public.phone_core(telefone)) stored;
alter table public.compras
  add column if not exists telefone_core text generated always as (public.phone_core(telefone)) stored;

create index if not exists recovery_events_core_idx on public.recovery_events (telefone_core);
create index if not exists compras_core_idx          on public.compras (telefone_core, compra_em desc);

-- View da conversão: 1 linha por evento de recuperação, com converteu +
-- valor_recuperado, cruzando com a compra mais recente do mesmo telefone.
create or replace view public.v_recovery_conversao as
select
  re.id,
  re.evento_em,
  re.tipo,
  re.nome,
  re.telefone,
  re.valor,
  (c.compra_em is not null
     and (c.compra_em at time zone 'America/Sao_Paulo')::date
         >= (re.evento_em at time zone 'America/Sao_Paulo')::date
  ) as converteu,
  case when c.compra_em is not null
        and (c.compra_em at time zone 'America/Sao_Paulo')::date
            >= (re.evento_em at time zone 'America/Sao_Paulo')::date
       then c.valor else 0 end as valor_recuperado,
  c.compra_em  as data_pagamento,
  c.produto    as produto_comprado
from public.recovery_events re
left join lateral (
  select valor, compra_em, produto
  from public.compras c
  where c.telefone_core = re.telefone_core
  order by c.compra_em desc
  limit 1
) c on re.telefone_core is not null and re.telefone_core <> '';  -- evento sem telefone nunca casa
