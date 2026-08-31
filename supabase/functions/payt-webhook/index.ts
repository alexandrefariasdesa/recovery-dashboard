// =============================================================================
// supabase/functions/payt-webhook/index.ts  (projeto recovery-dashboard)
// Recebe o webhook de transação da Payt e grava UMA linha em `recovery_events`.
//
// POR QUE EXISTE: hoje o webhook da Payt vai pro Make, que faz DUAS coisas —
// Add Row no Sheets E dispara o ManyChat. Este receptor roda EM PARALELO ao
// Make (fan-out): a Payt manda pros dois, ou o Make encaminha uma cópia pra cá.
// Assim o Postgres começa a receber os eventos SEM tocar no disparo do ManyChat.
// Quando o Postgres virar a fonte da verdade, o Make sai de cena.
//
// AUTENTICAÇÃO: ?token=SHARED_TOKEN (a Payt/Make manda igual). Sem token, recusa.
//
// DESCOBERTA DO PAYLOAD: a forma exata do webhook da Payt não está documentada
// aqui, então logamos o corpo INTEIRO em toda chamada e mapeamos por uma lista
// de caminhos plausíveis (mesmo padrão que funcionou no Hotmart do quizfunnel).
// A primeira transação real revela os campos certos no log; aí a gente fixa.
//
// SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são injetados automaticamente nas
// edge functions — o insert roda como service_role e ignora a RLS.
// =============================================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SHARED_TOKEN = Deno.env.get("PAYT_WEBHOOK_TOKEN") ?? "";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

// Leitor de caminho aninhado: g("customer.phone").
function reader(b: Record<string, unknown>) {
  return (path: string): unknown =>
    path.split(".").reduce<unknown>(
      (o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined),
      b,
    );
}
function pick(g: (p: string) => unknown, ...paths: string[]): string | null {
  for (const p of paths) {
    const v = g(p);
    if (typeof v === "string" && v.trim()) return v.trim();
    if (typeof v === "number") return String(v);
  }
  return null;
}

const onlyDigits = (s: string | null) => (s ?? "").replace(/\D/g, "");

// ── UTM: de onde a venda veio ────────────────────────────────────────────────
// A pessoa que compra depois do fluxo de boas-vindas do Instagram não deixa
// telefone no fluxo, então não há identidade para casar com `manychat_eventos`.
// O que sobra é a origem do clique, e a Payt carrega isso no payload. Não temos
// a forma exata documentada, então varremos os lugares plausíveis e guardamos
// TUDO que parecer UTM — inclusive chaves que ainda não conhecemos.
// `src`, `sck` e `xcod` são os parâmetros de rastreio da Payt (mesma família do
// Hotmart) — o fluxo manda a mesma etiqueta nos três. `utm_*` entram junto
// porque o link pode carregar os dois formatos.
//
// E eles vêm ANINHADOS, não no topo do payload. Confirmado numa compra aprovada
// real em 31/08/2026:
//   link.sources      → src, utm_source, utm_medium, utm_campaign, utm_content,
//                       utm_term (o que estava na URL do checkout)
//   link.query_params → sck, clickid (o que a plataforma anexou)
// Procurar só no topo devolvia sempre vazio.
const UTM_KEYS = new Set([
  "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "utm_id",
  "src", "sck", "xcod", "source", "origem", "clickid",
]);

// Onde procurar, em ordem. A primeira ocorrência de uma chave vence — o topo é
// mais confiável que o aninhado quando as duas existem.
const UTM_PATHS = [
  "", "link.sources", "link.query_params", "link",
  "transaction", "tracking", "utms", "utm", "data", "checkout", "order",
];

function noCaminho(body: Record<string, unknown>, caminho: string): unknown {
  if (!caminho) return body;
  return caminho.split(".").reduce<unknown>(
    (o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined),
    body,
  );
}

function colherUtm(body: Record<string, unknown>): Record<string, string> | null {
  const out: Record<string, string> = {};

  const absorve = (obj: unknown) => {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return;
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      const chave = k.toLowerCase();
      if (typeof v !== "string" && typeof v !== "number") continue;
      const valor = String(v).trim();
      if (!valor) continue;
      if (UTM_KEYS.has(chave) || chave.startsWith("utm")) out[chave] ??= valor;
    }
  };

  for (const caminho of UTM_PATHS) absorve(noCaminho(body, caminho));

  return Object.keys(out).length ? out : null;
}

// Valor pode vir em reais (float) ou centavos (int). Heurística: inteiro >= 1000
// sem casa decimal provavelmente é centavos. (Fallback; a Payt usa centavos.)
function toReais(raw: string | null): number | null {
  if (raw == null) return null;
  const n = Number(raw);
  if (isNaN(n)) return null;
  if (Number.isInteger(n) && Math.abs(n) >= 1000) return n / 100;
  return n;
}

// A Payt manda timestamp naïve "2026-07-26 00:49:17" (sem T, sem fuso). É horário
// local do Brasil (São Paulo, UTC-3). Sem carimbar o fuso, o V8 interpretaria em
// UTC e a data poderia pular um dia perto da meia-noite.
function parsePaytDate(s: string | null): Date {
  if (!s) return new Date();
  const t = s.trim().replace(" ", "T");
  const jaTemFuso = /[zZ]|[+-]\d\d:?\d\d$/.test(t);
  const d = new Date(jaTemFuso ? t : t + "-03:00");
  return isNaN(d.getTime()) ? new Date() : d;
}

// Deriva o tipo do evento a partir de payment_method + status/event. Liberal:
// Método de pagamento (pix|boleto) A PARTIR DO PAYLOAD. É a peça que NÃO dá pra
// carimbar na URL: na Payt, "gerado" é um evento só pra pix e boleto (idem
// "expirado"), então o método tem que vir do corpo. Liberal nos caminhos.
function metodoDoPayload(g: (p: string) => unknown): "pix" | "boleto" | null {
  const method = (pick(g, "payment_method", "transaction.payment_method", "data.payment_method", "method", "payment_type") ?? "").toLowerCase();
  if (/pix/.test(method)) return "pix";
  if (/boleto|bank_slip|billet/.test(method)) return "boleto";
  return null;
}

// Derivação COMPLETA (método + estágio) só do payload — usada como fallback
// quando a URL não carimba nem tipo nem evento. Se não reconhecer, devolve o
// texto cru (nada se perde; a gente corrige pelo log).
function derivarTipo(g: (p: string) => unknown): string {
  const status = (pick(g, "status", "transaction.status", "data.status") ?? "").toLowerCase();
  const event = (pick(g, "event", "type", "event_type", "data.event") ?? "").toLowerCase();

  const isAbandono = /abandon|cart|checkout/.test(event) || status === "abandoned";
  if (isAbandono) return "carrinho_abandonado";

  const expirado = /expired|overdue|expirado|vencid/.test(status) || /expired|overdue/.test(event);
  const gerado = /waiting|pending|created|generated|gerad|aguard/.test(status) || /created|generated/.test(event);
  const metodo = metodoDoPayload(g);

  if (metodo && expirado) return `${metodo}_expirado`;
  if (metodo && gerado) return `${metodo}_gerado`;

  return `desconhecido:${metodo ?? "?"}:${status || event || "?"}`;
}

Deno.serve(async (req) => {
  if (req.method === "GET") return json({ ok: true, service: "payt-webhook" });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  const raw = await req.text();
  let parsed: unknown = {};
  try { parsed = JSON.parse(raw); } catch { parsed = Object.fromEntries(new URLSearchParams(raw)); }
  // A PAYT MANDA O CORPO COMO ARRAY DE 1 OBJETO: [ { ... } ]. Desembrulha —
  // era isso que fazia todo caminho aninhado (método, valor) voltar vazio.
  const body = (Array.isArray(parsed) ? (parsed[0] ?? {}) : parsed) as Record<string, unknown>;

  const g = reader(body);
  const tipoParam = (url.searchParams.get("tipo") ?? "").trim().toLowerCase();
  const eventoHint = (url.searchParams.get("evento") ?? "").trim().toLowerCase(); // gerado|expirado|aprovado

  // Campos comuns aos dois destinos (recovery_events e compras).
  const nome = pick(g, "customer.name", "transaction.customer.name", "data.customer.name", "name", "buyer.name");
  const email = pick(g, "customer.email", "transaction.customer.email", "data.customer.email", "email", "buyer.email");
  const telefone = onlyDigits(pick(g, "customer.phone", "transaction.customer.phone", "data.customer.phone", "phone", "buyer.phone", "whatsapp"));
  // Payt: valor em CENTAVOS em transaction.total_price / product.price.
  const centavos = pick(g, "transaction.total_price", "total_price", "product.price");
  const valor = (centavos != null && !isNaN(Number(centavos)))
    ? Number(centavos) / 100
    : toReais(pick(g, "amount", "value", "total"));

  if (!telefone) {
    // Sem telefone não dá pra cruzar conversão. Aceita (200) pra Payt não reenviar.
    console.error("payt-webhook: sem telefone no payload:", raw.slice(0, 2000));
    return json({ ok: true, stored: false, reason: "no_phone" });
  }

  const admin = createClient(SUPABASE_URL, SERVICE_KEY);

  // ── COMPRA APROVADA → tabela `compras` (o lado da conversão) ──────────────
  if (eventoHint === "aprovado") {
    const compraEm = parsePaytDate(
      pick(g, "transaction.updated_at", "transaction.created_at", "updated_at", "created_at", "started_at"),
    );
    const transactionId = pick(g, "transaction_id", "transaction.transaction_id", "id");
    const produto = pick(g, "product.name", "transaction.product.name", "product_name");

    // UPSELL: a operação roda vários (Protocolo do Prazer, Safada na Hora Certa,
    // entre outros) e cada um é uma TRANSAÇÃO PRÓPRIA na Payt, com `type:
    // "upsell"` no topo e `transaction.upsell_from` apontando pra compra que o
    // gerou. Sem separar, o upsell entraria como se fosse uma compra de entrada
    // e viraria a "última compra" da pessoa — a conversão da recuperação passaria
    // a valer R$ 27 em vez dos R$ 76,90 que ela de fato pagou.
    const upsellDe = pick(g, "transaction.upsell_from", "upsell_from", "upsell_code");
    // `?venda=upsell|front` na URL vence o payload. A detecção automática depende
    // de a Payt marcar `type: "upsell"` ou mandar `upsell_from` — se uma oferta
    // não mandar nenhum dos dois, a venda entraria como front e contaminaria a
    // conversão (ver 0014). Cravar na URL da oferta é a trava pra esse caso.
    const vendaParam = (url.searchParams.get("venda") ?? "").trim().toLowerCase();
    const ehUpsell = vendaParam === "upsell" ? true
      : vendaParam === "front" ? false
      : ((pick(g, "type", "transaction.type") ?? "").toLowerCase() === "upsell"
         || !!pick(g, "transaction.upsell_from", "upsell_from"));
    // Origem da venda. `utm` é a chave de atribuição de fluxo (ver migration
    // 0020); `raw` guarda o payload inteiro para que um parâmetro com nome
    // inesperado possa ser recuperado por backfill, sem novo deploy.
    const utm = colherUtm(body);
    const compraRow: Record<string, unknown> = {
      compra_em: isNaN(compraEm.getTime()) ? new Date().toISOString() : compraEm.toISOString(),
      nome, email, telefone, valor, produto, transaction_id: transactionId,
      tipo: ehUpsell ? "upsell" : "front",
      upsell_de: ehUpsell ? upsellDe : null,
      utm,
      raw: body,
    };
    // Upsert por transaction_id: reenvio da Payt não duplica a compra (o que
    // inflaria a conversão). Sem transaction_id, insere direto.
    const { error } = transactionId
      ? await admin.from("compras").upsert(compraRow, { onConflict: "transaction_id", ignoreDuplicates: true })
      : await admin.from("compras").insert(compraRow);
    if (error) { console.error("payt-webhook compras:", error.message); return json({ error: error.message }, 500); }

    // A MESMA compra chega em dois lugares: aqui e no Make, que grava a linha
    // direto no Postgres. Quem inserir primeiro vence, e o upsert acima é
    // `ignoreDuplicates` — então, quando o Make ganha a corrida, a linha fica
    // sem origem e a atribuição do fluxo se perde. Este update preenche só o que
    // falta (origem e payload), sem tocar em mais nada da linha existente.
    if (transactionId && utm) {
      const { error: erroUtm } = await admin.from("compras")
        .update({ utm, raw: body })
        .eq("transaction_id", transactionId)
        .is("utm", null);
      if (erroUtm) console.error("payt-webhook utm backfill:", erroUtm.message);
    }
    return json({ ok: true, stored: true, destino: "compras", tipo: compraRow.tipo, telefone, valor, utm });
  }

  // ── EVENTO DE RECUPERAÇÃO → tabela `recovery_events` ──────────────────────
  //  1) ?tipo=<completo> — carrinho_abandonado (sem ambiguidade de método).
  //  2) ?evento=gerado|expirado — estágio na URL, método do payload.
  //  3) sem nada — deriva do payload.
  const TIPOS_VALIDOS = new Set([
    "pix_gerado", "pix_expirado", "boleto_gerado", "boleto_expirado", "carrinho_abandonado",
  ]);
  let tipo: string;
  if (TIPOS_VALIDOS.has(tipoParam)) {
    tipo = tipoParam;
  } else if (eventoHint === "gerado" || eventoHint === "expirado") {
    const metodo = metodoDoPayload(g);
    tipo = metodo ? `${metodo}_${eventoHint}` : `desconhecido:${eventoHint}:sem_metodo`;
  } else {
    tipo = derivarTipo(g);
  }
  if (tipo.startsWith("desconhecido")) {
    console.error("payt-webhook: tipo não resolvido:", tipo, "| payload:", raw.slice(0, 4000));
  }

  const eventoEm = parsePaytDate(
    pick(g, "transaction.created_at", "started_at", "created_at", "transaction.updated_at", "updated_at"),
  );
  const row: Record<string, unknown> = {
    evento_em: isNaN(eventoEm.getTime()) ? new Date().toISOString() : eventoEm.toISOString(),
    tipo, nome, telefone, valor,
  };
  // Auto-diagnóstico: tipo não resolvido guarda o payload cru (casos raros).
  if (tipo.startsWith("desconhecido")) row.raw = body;

  const { error } = await admin.from("recovery_events").insert(row);
  if (error) {
    console.error("payt-webhook: insert falhou:", error.message);
    return json({ error: error.message }, 500);
  }

  return json({ ok: true, stored: true, tipo, telefone, valor });
});
