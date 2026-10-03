-- 0025 — janela de horário por etapa da recuperação (fuso Manaus).
-- janela_ini/janela_fim nulos = sem trava (comportamento antigo). Fora da janela
-- a etapa continua 'agendado' e sai quando a janela abre.
alter table public.recuperacao_etapas
  add column if not exists janela_ini time,
  add column if not exists janela_fim time;

do $m$
declare def text;
begin
  def := pg_get_functiondef('public.fila_recuperacao(integer,integer)'::regprocedure);
  if def not like '%janela_ini%' then
    def := replace(def, E'     and et.ativo\n',
      E'     and et.ativo\n     and (et.janela_ini is null or et.janela_fim is null\n          or (now() at time zone ''America/Manaus'')::time between et.janela_ini and et.janela_fim)\n');
    execute def;
  end if;
end $m$;
