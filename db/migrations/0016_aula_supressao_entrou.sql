-- =============================================================================
-- 0016_aula_supressao_entrou.sql — quem já está na sala para de ser chamado
--
-- O DEFEITO QUE ISSO CONSERTA: as etapas `ao_vivo` (19h15) e `comecamos`
-- (19h30) vão hoje pra TODA convidada do dia, inclusive pra quem já entrou na
-- sala. A pessoa está assistindo desde 19h10 e às 19h30 recebe no WhatsApp um
-- "COMEÇOU AGORA 🔴 Tô ao vivo te esperando, vem 💗". Não era possível evitar
-- antes do 0015: não existia nenhuma linha no banco dizendo que ela entrou.
--
-- Com `aula_eventos` recebendo o webhook `entrou_sala` da Applive, dá. E o
-- desenho é o mesmo da recuperação, que já roda há semanas: lá, quem comprou
-- sai da fila ('ja comprou'); aqui, quem entrou sai da fila ('ja entrou').
--
-- POR ETAPA, NÃO GLOBAL: `falta_1h` (18h30) avisa que falta uma hora — a sala
-- nem abriu, ninguém entrou, e suprimir não faria sentido. Por isso a decisão
-- vira uma COLUNA na tabela de etapas em vez de uma regra fixa no SQL: dá pra
-- ligar e desligar por mensagem, sem migration nova.
--
-- A junção com o evento é por telefone_core (a chave do sistema) OU e-mail,
-- porque num webinário é comum o evento sair só com e-mail. Idempotente.
-- =============================================================================

-- ── A decisão vira dado ──────────────────────────────────────────────────────
alter table public.convites_aula_etapas
  add column if not exists pular_se_entrou boolean not null default false;

comment on column public.convites_aula_etapas.pular_se_entrou is
  'true = não manda pra quem já tem evento entrou_sala na aula de hoje. '
  'Ligado nas mensagens que chamam pra entrar (ao_vivo, comecamos).';

-- As duas que chamam pra sala. `e_hoje` (09h) e `falta_1h` (18h30) acontecem
-- antes de a sala abrir, então continuam indo pra todo mundo.
update public.convites_aula_etapas set pular_se_entrou = true
 where etapa in ('ao_vivo', 'comecamos');

-- ── Registrar a supressão, em vez de só omitir ───────────────────────────────
-- Sem isso, a pessoa suprimida some da fila e nunca mais aparece: o painel
-- mostraria "180 convidadas, 120 enviadas" e ninguém saberia se as 60 que
-- faltaram foram suprimidas ou se o disparo quebrou. `suprimida` é a diferença
-- entre uma mensagem que a gente decidiu não mandar e uma que falhou.
alter table public.convites_aula_envios
  drop constraint if exists convites_aula_envios_status_check;
alter table public.convites_aula_envios
  add constraint convites_aula_envios_status_check
  check (status in ('enviada', 'erro', 'suprimida'));

-- ── Quem entrou na sala hoje ─────────────────────────────────────────────────
-- Uma view só pra não repetir a regra nos dois lugares que precisam dela (a
-- fila e a marcação). `entrou_sala` é o nome que a gente escolheu ao cadastrar
-- o webhook (?evento=entrou_sala) — não é um nome que a plataforma impôs.
create or replace view public.v_aula_entrou_hoje as
select distinct
  nullif(e.telefone_core, '') as telefone_core,
  lower(nullif(e.email, ''))  as email
from public.aula_eventos e
where e.evento = 'entrou_sala'
  and (e.evento_em at time zone 'America/Sao_Paulo')::date
      = (now() at time zone 'America/Sao_Paulo')::date;

comment on view public.v_aula_entrou_hoje is
  'Chaves de quem já está na sala HOJE. Alimenta a supressão das etapas que '
  'chamam pra entrar.';

-- ── Marca as suprimidas (roda antes de cada etapa) ───────────────────────────
-- Espelha cancelar_recuperacoes_compradas() do 0008: mesma forma, mesmo lugar
-- no ciclo, mesmo motivo textual guardado.
create or replace function public.suprimir_convites_ja_entraram(p_etapa text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  -- Etapa que não pede supressão sai fora sem tocar em nada.
  if not exists (select 1 from public.convites_aula_etapas
                  where etapa = p_etapa and pular_se_entrou) then
    return 0;
  end if;

  insert into public.convites_aula_envios
    (convite_id, etapa, aula_data, status, tentativas, erro)
  select ca.id, p_etapa, (now() at time zone 'America/Sao_Paulo')::date,
         'suprimida', 0, 'ja entrou na sala'
  from public.convites_aula ca
  where ca.status = 'enviada'
    and ca.aula_data = (now() at time zone 'America/Sao_Paulo')::date
    and exists (
      select 1 from public.v_aula_entrou_hoje x
       where (x.telefone_core is not null and x.telefone_core = ca.telefone_core)
          or (x.email is not null and x.email = lower(ca.email))
    )
  on conflict (convite_id, etapa, aula_data) do nothing;

  get diagnostics n = row_count;
  return n;
end;
$$;

-- ── A fila passa a respeitar a supressão ─────────────────────────────────────
-- Cinto e suspensório: a marcação acima já tira a pessoa (a linha 'suprimida'
-- faz o left join achar algo e o filtro de status a exclui), mas o NOT EXISTS
-- explícito garante que ninguém escape se o webhook `entrou_sala` chegar entre
-- a marcação e a leitura da fila — que é exatamente a janela dos 19h15/19h30,
-- quando as pessoas estão entrando ao vivo.
drop function if exists public.fila_convites_etapa(text, int, int);

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
