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

// Valor pode vir em reais (float) ou centavos (int). Heurística: inteiro >= 1000
// sem casa decimal provavelmente é centavos.
function toReais(raw: string | null): number | null {
  if (raw == null) return null;
  const n = Number(raw);
  if (isNaN(n)) return null;
  if (Number.isInteger(n) && Math.abs(n) >= 1000) return n / 100;
  return n;
}

// Deriva o tipo do evento a partir de payment_method + status/event. Liberal:
// se não reconhecer, devolve o texto cru (nada se perde; a gente corrige depois).
function derivarTipo(g: (p: string) => unknown): string {
  const method = (pick(g, "payment_method", "transaction.payment_method", "data.payment_method", "method") ?? "").toLowerCase();
  const status = (pick(g, "status", "transaction.status", "data.status") ?? "").toLowerCase();
  const event = (pick(g, "event", "type", "event_type", "data.event") ?? "").toLowerCase();

  const isAbandono = /abandon|cart|checkout/.test(event) || status === "abandoned";
  if (isAbandono) return "carrinho_abandonado";

  const expirado = /expired|overdue|expirado|vencid/.test(status) || /expired|overdue/.test(event);
  const gerado = /waiting|pending|created|generated|gerad|aguard/.test(status) || /created|generated/.test(event);

  const isPix = /pix/.test(method) || /pix/.test(event);
  const isBoleto = /boleto|bank_slip|billet/.test(method) || /boleto/.test(event);

  if (isPix && expirado) return "pix_expirado";
  if (isPix && gerado) return "pix_gerado";
  if (isBoleto && expirado) return "boleto_expirado";
  if (isBoleto && gerado) return "boleto_gerado";

  // Não reconhecido: guarda o cru pra não perder o evento (visível no dashboard
  // como tipo "estranho" e no log com o payload inteiro).
  return `desconhecido:${method || "?"}:${status || event || "?"}`;
}

Deno.serve(async (req) => {
  if (req.method === "GET") return json({ ok: true, service: "payt-webhook" });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  const raw = await req.text();
  let body: Record<string, unknown> = {};
  try { body = JSON.parse(raw); } catch { body = Object.fromEntries(new URLSearchParams(raw)); }

  // LOG DE DESCOBERTA: payload inteiro em toda chamada. Tirar quando o mapa
  // estiver confirmado com evento real.
  console.log("payt-webhook payload:", raw.slice(0, 4000));

  const g = reader(body);
  const tipo = derivarTipo(g);
  const nome = pick(g, "customer.name", "transaction.customer.name", "data.customer.name", "name", "buyer.name");
  const telefone = onlyDigits(pick(g, "customer.phone", "transaction.customer.phone", "data.customer.phone", "phone", "buyer.phone", "whatsapp"));
  const valor = toReais(pick(g, "amount", "value", "total", "transaction.amount", "data.amount", "price"));
  const eventoEmRaw = pick(g, "created_at", "date", "transaction.created_at", "data.created_at", "updated_at", "occurred_at");
  const eventoEm = eventoEmRaw ? new Date(eventoEmRaw) : new Date();

  if (!telefone) {
    // Sem telefone não dá pra cruzar conversão. Loga e aceita (200) pra Payt não
    // ficar reenviando durante a descoberta — o payload no log resolve o mapa.
    console.error("payt-webhook: sem telefone no payload:", raw.slice(0, 2000));
    return json({ ok: true, stored: false, reason: "no_phone", tipo });
  }

  const admin = createClient(SUPABASE_URL, SERVICE_KEY);
  const { error } = await admin.from("recovery_events").insert({
    evento_em: isNaN(eventoEm.getTime()) ? new Date().toISOString() : eventoEm.toISOString(),
    tipo,
    nome,
    telefone,
    valor,
  });
  if (error) {
    console.error("payt-webhook: insert falhou:", error.message);
    // 500 faz a Payt reenviar — bom pra não perder o evento por erro transitório.
    return json({ error: error.message }, 500);
  }

  return json({ ok: true, stored: true, tipo, telefone, valor });
});
