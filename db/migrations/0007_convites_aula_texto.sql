-- =============================================================================
-- 0007_convites_aula_texto.sql — a copy de cada etapa vive no banco
--
-- Todos os templates aprovados da conta são montados em cima de dois campos
-- (`p1` = cuf_13923586, `p2` = cuf_13923587): o corpo aprovado é só "Status
-- atualizado / {{p1}} / {{p2}} / <chamada>". Ou seja: dá pra mandar qualquer
-- texto como TEMPLATE — que é o que faz a mensagem chegar mesmo em quem nunca
-- respondeu (janela de 24h do WhatsApp fechada).
--
-- Então a edge function grava p1/p2 no contato ANTES do sendFlow, e o fluxo do
-- ManyChat fica com 2 tijolos: condição (clicou_aula = 'bloqueou' -> fim) e o
-- template. Trocar a copy = update aqui, sem tocar no ManyChat.
--
-- `{link}` em qualquer um dos textos é trocado pelo link_sala daquela pessoa
-- (Applive pré-preenchido, gravado em convites_aula na fase das 09h).
-- Idempotente.
-- =============================================================================

alter table public.convites_aula_etapas add column if not exists texto_p1 text;
alter table public.convites_aula_etapas add column if not exists texto_p2 text;
alter table public.convites_aula_etapas add column if not exists template text;

comment on column public.convites_aula_etapas.texto_p1 is
  'Vai pro campo p1 (cuf_13923586) antes do sendFlow. {link} vira o link_sala da pessoa.';
comment on column public.convites_aula_etapas.texto_p2 is
  'Vai pro campo p2 (cuf_13923587) antes do sendFlow. {link} vira o link_sala da pessoa.';
comment on column public.convites_aula_etapas.template is
  'Template aprovado usado pelo fluxo dessa etapa. Documental: quem escolhe é o fluxo no ManyChat.';

update public.convites_aula_etapas set
  template = 'e_hoje_2',
  texto_p1 = 'Hoje é o dia 💗 Às *19h30* eu vou estar ao vivo com você, de graça.',
  texto_p2 = 'Toca no botão aqui embaixo que eu guardo o teu lugar 😍'
where etapa = 'e_hoje';

update public.convites_aula_etapas set
  template = 'e_hoje_2',
  texto_p1 = '⏰ Falta 1 hora. A nossa aula começa *19h30*, ao vivo.',
  texto_p2 = 'Toca no botão aqui embaixo que eu te mando o link da sala 💗'
where etapa = 'falta_1h';

update public.convites_aula_etapas set
  template = 'estou_ao_vivo',
  texto_p1 = 'ABRIU A SALA 🔥 Começa *19h30* — entra agora pra garantir teu lugar.',
  texto_p2 = '{link}'
where etapa = 'ao_vivo';

update public.convites_aula_etapas set
  template = 'estou_ao_vivo',
  texto_p1 = 'COMEÇOU AGORA 🔴 Tô ao vivo te esperando, vem 💗',
  texto_p2 = '{link}'
where etapa = 'comecamos';

-- A fila passa a devolver o link_sala da pessoa (pro {link} dos textos).
-- Mudou a assinatura de saída, então precisa dropar antes de recriar.
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
  order by ca.id
  limit p_limite;
$$;
