-- 0026 — `desde` por etapa. Sem isso, ligar uma etapa nova varreria TODOS os
-- eventos desde recuperacao_config.desde e dispararia a etapa pra histórico antigo.
alter table public.recuperacao_etapas add column if not exists desde timestamptz;

do $m$
declare def text;
begin
  def := pg_get_functiondef('public.agendar_recuperacoes(integer)'::regprocedure);
  if def not like '%et.desde%' then
    def := replace(def, E'and ev.evento_em >= cfg.desde\n',
                        E'and ev.evento_em >= greatest(cfg.desde, coalesce(et.desde, cfg.desde))\n');
    execute def;
  end if;
end $m$;

-- etapa 2 do PIX expirado: criada DESLIGADA; 24h, janela 8h-21h (Manaus)
insert into public.recuperacao_etapas (tipo, etapa, ordem, atraso, flow_ns, link_fallback, ativo, janela_ini, janela_fim)
select 'pix_expirado','lembrete_2',2,interval '24 hours','content20261003124150_044730',link_fallback,false,'08:00','21:00'
from public.recuperacao_etapas where tipo='pix_expirado' and etapa='lembrete'
on conflict do nothing;
