-- =============================================================================
-- 0010_supressao_por_produto.sql — a supressão passa a olhar QUAL produto
--
-- `cancelar_recuperacoes_compradas()` cancela a recuperação quando existe uma
-- compra do mesmo telefone depois do evento. Isso funcionou enquanto `compras`
-- só tinha um produto: toda linha ali era, necessariamente, a venda daquele
-- funil.
--
-- Deixa de valer agora que a venda do Protocolo do Prazer passa a entrar na
-- mesma tabela (pelo External Request do fluxo do ManyChat, já que a oferta
-- não manda webhook pra cá). Sem filtro, comprar o Protocolo cancelaria o
-- lembrete de um PIX de Posições que continua em aberto — a pessoa some da
-- recuperação por ter comprado outra coisa.
--
-- `recuperacao_config.produto_like` já existe e já significa "o produto deste
-- funil": na origem `compra` ele diz qual venda dispara. Aqui ele passa a
-- dizer, na origem `evento`, qual venda cancela. Nulo = comportamento antigo
-- (qualquer compra cancela), então nada muda pra quem não declarar.
-- Idempotente.
-- =============================================================================

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
    join public.recuperacao_config cfg on cfg.tipo = ev.tipo
   where ev.id = d.evento_id
     and d.status = 'agendado'
     and exists (
       select 1 from public.compras c
        where c.telefone_core = d.telefone_core
          and c.compra_em >= ev.evento_em
          and (cfg.produto_like is null or c.produto ilike cfg.produto_like)
     );
  get diagnostics n = row_count;
  return n;
end;
$$;

-- Os quatro funis de recuperação são todos de Posições Secretas — é o único
-- produto que gera PIX/boleto/carrinho rastreado aqui.
update public.recuperacao_config
   set produto_like = '%posi%'
 where origem = 'evento' and produto_like is null;
