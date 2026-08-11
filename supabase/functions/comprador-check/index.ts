// =============================================================================
// supabase/functions/comprador-check/index.ts  (projeto recovery-dashboard)
// Supressão da recuperação de carrinho: responde se o telefone já COMPROU,
// consultando a tabela `compras` (backfill da planilha COMPRADORES/Leads +
// compras novas ao vivo via payt-webhook ?evento=aprovado).
//
// Substitui o "Search Rows" do Make na planilha Leads. Vantagem além da cota
// do Sheets: o match usa telefone_core, que colapsa as variantes com/sem o 9
// e com/sem o 55 — o Search Rows compara texto exato e deixa passar comprador
// com o número em outro formato.
//
// USO (Make, módulo HTTP — GET ou POST):
//   GET  .../comprador-check?token=<TOKEN>&phone=5592994305962
//   POST .../comprador-check?token=<TOKEN>   body JSON: {"phone": "..."}
//        (aceita também Full Contact Data do ManyChat: customer.phone etc.)
// Resposta: {"comprador":"sim"} ou {"comprador":"nao"}
//
// FAIL-OPEN: qualquer erro de banco responde {"comprador":"nao"} com 200 —
// melhor disparar recuperação pra um comprador do que travar o fluxo inteiro.
// (Token errado ainda é 401: erro de configuração deve aparecer, não sumir.)
// =============================================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SHARED_TOKEN = Deno.env.get("COMPRADOR_CHECK_TOKEN") ?? "";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

// Espelha public.phone_core (migration 0003) / utils.normalize_phone:
// só dígitos → tira o 55 do país → celular de 11 díg (DDD+9+8) vira 10 (DDD+8).
// Assim "5592994305962", "92994305962" e "9294305962" dão a MESMA chave.
function phoneCore(raw: string): string {
  let d = raw.replace(/\D/g, "");
  if (d.length >= 12 && d.startsWith("55")) d = d.slice(2);
  if (d.length === 11 && d[2] === "9") d = d.slice(0, 2) + d.slice(3);
  return d;
}

// Acha o telefone no body: chave direta ou Full Contact Data do ManyChat.
function phoneFromBody(b: Record<string, unknown>): string {
  const paths = [
    ["phone"], ["telefone"], ["whatsapp"], ["whatsapp_phone"],
    ["customer", "phone"], ["contact", "phone"], ["data", "phone"],
  ];
  for (const p of paths) {
    const v = p.reduce<unknown>(
      (o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined),
      b,
    );
    if (typeof v === "string" && v.trim()) return v;
    if (typeof v === "number") return String(v);
  }
  return "";
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  let phone = url.searchParams.get("phone") ?? "";
  if (!phone && req.method === "POST") {
    const raw = await req.text();
    let parsed: unknown = {};
    try { parsed = JSON.parse(raw); } catch { parsed = Object.fromEntries(new URLSearchParams(raw)); }
    const body = (Array.isArray(parsed) ? (parsed[0] ?? {}) : parsed) as Record<string, unknown>;
    phone = phoneFromBody(body);
  }

  const core = phoneCore(phone);
  // Telefone vazio/curto demais nunca casa (mesmo guard da view de conversão).
  if (core.length < 8) return json({ comprador: "nao", reason: "no_phone" });

  try {
    const admin = createClient(SUPABASE_URL, SERVICE_KEY);
    const { data, error } = await admin
      .from("compras")
      .select("id")
      .eq("telefone_core", core)
      .limit(1);
    if (error) throw new Error(error.message);
    return json({ comprador: data && data.length > 0 ? "sim" : "nao" });
  } catch (e) {
    // Fail-open: o disparo segue.
    console.error("comprador-check:", e instanceof Error ? e.message : e);
    return json({ comprador: "nao", reason: "error" });
  }
});
