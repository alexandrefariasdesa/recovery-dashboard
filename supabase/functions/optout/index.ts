// =============================================================================
// supabase/functions/optout/index.ts  (projeto recovery-dashboard)
// Lista de bloqueio do disparo por API — os três blocos do ManyChat.
//
//   BLOQUEAR    → POST /optout?acao=bloquear&token=...&origem=<slug>
//   DESBLOQUEAR → POST /optout?acao=desbloquear&token=...&origem=<slug>
//   CHECAR      → POST /optout?acao=checar&token=...   (ou GET ...&phone=...)
//   body: Full Contact Data (1 clique no ManyChat) → traz { phone, id, name }
//
// Grava em `public.optout` (0018) pelo telefone_core — a mesma chave que
// colapsa o número com e sem o 9. A partir daí a pessoa some das filas de
// `recuperacao-disparo` e `aula-convite`: nenhuma mensagem por API sai pra ela.
// Desbloquear devolve o número pras filas sem apagar o histórico.
//
// `checar` é a consulta pra pôr ANTES de qualquer disparo — dentro do fluxo do
// ManyChat, no Make, ou em qualquer coisa que mande mensagem sem passar pelas
// filas do banco. Não grava nada, só responde.
//
// Resposta (pro Response Mapping do ManyChat):
//   { "ok": true, "bloqueado": "sim" | "nao", "disparar": "sim" | "nao",
//     "ja_estava": true|false, "telefone": "<core>" }
//
// FAIL-CLOSED de propósito, ao contrário do comprador-check:
//   - bloquear/desbloquear: se o banco cair, devolve 502 e o ManyChat mostra o
//     erro — melhor a pessoa tocar de novo do que sair achando que bloqueou.
//   - checar: em caso de erro responde `disparar: "nao"` (não manda). Mandar
//     pra quem pediu pra sair é o que derruba a qualidade da conta; segurar a
//     mensagem custa um disparo. Pra inverter num fluxo específico:
//     &se_falhar=liberar.
//
// Opcional (só se MC_OPTOUT_FIELD estiver setado): carimba também um custom
// field no contato do ManyChat, pra os fluxos internos dele poderem ramificar
// sem consultar o banco. Falha aqui NÃO derruba a resposta — o banco é a
// verdade; o campo é conveniência.
//
// AUTENTICAÇÃO: ?token= (OPTOUT_TOKEN, ou RECUP_TOKEN / CONVITE_TOKEN como
// fallback — assim dá pra subir sem criar secret novo).
// =============================================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SHARED_TOKEN = Deno.env.get("OPTOUT_TOKEN") ||
  Deno.env.get("RECUP_TOKEN") || Deno.env.get("CONVITE_TOKEN") || "";
const MC_TOKEN = Deno.env.get("MC_TOKEN") ?? "";
// Nome (não id) do custom field opcional no ManyChat. Vazio = não carimba nada.
const MC_OPTOUT_FIELD = Deno.env.get("MC_OPTOUT_FIELD") ?? "";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// O Full Contact Data do ManyChat muda de forma entre canais; aceita as
// variantes de telefone e de nome em vez de exigir um JSON montado à mão.
function extrair(body: Record<string, unknown>) {
  const s = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
  const telefone = s(body.whatsapp_phone || body.phone || body.telefone || "");
  const nome = [s(body.first_name), s(body.last_name)].filter(Boolean).join(" ").trim() ||
    s(body.name) || s(body.nome);
  const mcId = s(body.id || body.subscriber_id || body.key);
  return { telefone, nome, mcId };
}

// Carimbo opcional no contato do ManyChat. Best-effort: erro só vira log.
async function carimbar(mcId: string, valor: string) {
  if (!MC_OPTOUT_FIELD || !MC_TOKEN || !mcId) return;
  try {
    const r = await fetch("https://api.manychat.com/fb/subscriber/setCustomFieldByName", {
      method: "POST",
      headers: { Authorization: `Bearer ${MC_TOKEN}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        subscriber_id: mcId, field_name: MC_OPTOUT_FIELD, field_value: valor,
      }),
    });
    if (!r.ok) console.error("optout setCustomFieldByName:", r.status, (await r.text()).slice(0, 200));
  } catch (e) {
    console.error("optout setCustomFieldByName:", String(e).slice(0, 200));
  }
}

Deno.serve(async (req) => {
  const url = new URL(req.url);

  // GET sem telefone = health check. GET com ?phone= = consulta (o jeito fácil
  // pro Make e pra qualquer módulo HTTP que não monta corpo).
  if (req.method === "GET" && !url.searchParams.get("phone")) {
    return json({ ok: true, service: "optout" });
  }
  if (req.method !== "POST" && req.method !== "GET") {
    return json({ error: "method not allowed" }, 405);
  }

  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  let body: Record<string, unknown> = {};
  if (req.method === "POST") {
    try {
      body = (await req.json()) as Record<string, unknown>;
    } catch {
      body = {};
    }
  }

  const acao = (
    (url.searchParams.get("acao") ?? String(body.acao ?? "")) ||
    (req.method === "GET" ? "checar" : "")
  ).trim().toLowerCase();
  if (acao !== "bloquear" && acao !== "desbloquear" && acao !== "checar") {
    return json({ error: "acao inválida (bloquear|desbloquear|checar)" }, 400);
  }

  const { telefone: doBody, nome, mcId } = extrair(body);
  const telefone = doBody || (url.searchParams.get("phone") ?? "");
  if (!telefone) {
    return json({ error: "telefone obrigatório no corpo (Full Contact Data) ou em ?phone=" }, 400);
  }

  // ── Consulta: não grava nada, só diz se pode disparar ──────────────────────
  if (acao === "checar") {
    const admin = createClient(SUPABASE_URL, SERVICE_KEY);
    const { data, error } = await admin.rpc("optout_bloqueado", { p_telefone: telefone });
    if (error) {
      // Fail-closed por padrão: na dúvida, não manda (qualidade da conta).
      const liberar = (url.searchParams.get("se_falhar") ?? "").toLowerCase() === "liberar";
      console.error(`optout checar ${telefone}:`, error.message);
      return json({
        ok: false, erro: error.message,
        bloqueado: liberar ? "nao" : "sim",
        disparar: liberar ? "sim" : "nao",
      }, 502);
    }
    const bloqueado = data === true;
    return json({
      ok: true,
      bloqueado: bloqueado ? "sim" : "nao",
      disparar: bloqueado ? "nao" : "sim",
    });
  }

  // `origem` marca de qual fluxo veio o toque — vai na query, como no
  // recovery-flow-tracker, pra copiar o bloco entre fluxos trocando só o slug.
  const origem = "manychat:" + (url.searchParams.get("origem") ??
    url.searchParams.get("fluxo") ?? "sem_origem");
  const motivo = url.searchParams.get("motivo") ?? null;

  const admin = createClient(SUPABASE_URL, SERVICE_KEY);
  const rpc = acao === "bloquear" ? "optout_bloquear" : "optout_desbloquear";
  const args: Record<string, unknown> = {
    p_telefone: telefone, p_origem: origem, p_motivo: motivo, p_mc_subscriber_id: mcId,
  };
  if (acao === "bloquear") args.p_nome = nome;

  const { data, error } = await admin.rpc(rpc, args);
  if (error) {
    // Fail-closed: nada foi gravado, então não diga que bloqueou.
    console.error(`optout ${acao} ${telefone}:`, error.message);
    return json({ ok: false, erro: error.message }, 502);
  }

  const r = (data ?? {}) as Record<string, unknown>;
  if (r.ok === false) return json({ ok: false, erro: r.erro ?? "falhou" }, 400);

  const bloqueado = acao === "bloquear";
  await carimbar(mcId, bloqueado ? "sim" : "nao");

  console.log(
    `optout ${acao}: ${r.telefone_core} (${origem})` + (r.ja_estava ? " [repetido]" : ""),
  );
  return json({
    ok: true,
    bloqueado: bloqueado ? "sim" : "nao",
    disparar: bloqueado ? "nao" : "sim",   // mesmo campo do `checar`
    ja_estava: Boolean(r.ja_estava),
    telefone: r.telefone_core ?? "",
  });
});
