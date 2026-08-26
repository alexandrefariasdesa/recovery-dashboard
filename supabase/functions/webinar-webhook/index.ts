// =============================================================================
// supabase/functions/webinar-webhook/index.ts  (projeto recovery-dashboard)
// Receptor ÚNICO pra todos os webhooks da plataforma de webinário (Applive).
//
// POR QUE UM SÓ: a decisão foi cadastrar TODOS os webhooks disponíveis. Uma
// função por evento significaria um deploy a cada webhook novo e uma lista de
// tipos pra manter à mão. Aqui é o contrário: uma URL, cadastrada N vezes no
// painel da plataforma, e o tipo do evento vem de fora —
//
//     .../webinar-webhook?token=XXX&evento=entrou_sala
//
// O `?evento=` na URL é o caminho confiável, porque é você quem escreve na hora
// de cadastrar e não depende da plataforma mandar um campo `event`. Se não vier,
// a função deriva do payload; se nem isso, grava como `nao_identificado` — e
// mesmo assim GUARDA a linha. Nada é descartado por não ser reconhecido: é a
// primeira aula que revela os nomes reais, e ela só revela o que foi gravado.
//
// SEMPRE 200 (menos token errado). Plataforma de webinário costuma desativar o
// webhook depois de alguns 500 seguidos — um payload estranho não pode custar o
// cadastro inteiro. O que não deu pra entender fica no log e na coluna `raw`.
//
// AUTENTICAÇÃO: ?token=WEBINAR_TOKEN (mesmo padrão do payt-webhook).
// =============================================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SHARED_TOKEN = Deno.env.get("WEBINAR_TOKEN") ?? "";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

// ── Leitura liberal do payload (mesmo motor do payt-webhook) ────────────────
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

// Nome canônico: minúsculo, sem acento, separado por _. "Entrou na Sala" e
// "entrou_na_sala" viram a mesma chave — senão o catálogo do painel mostraria
// o mesmo evento duas vezes só por causa de maiúscula.
function canonizar(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "nao_identificado";
}

// Data: aceita ISO, naïve, e epoch (seg ou ms). Naïve sem fuso é horário do
// Brasil — mesma decisão do payt-webhook, pelo mesmo motivo (sem carimbar o
// fuso, o V8 lê como UTC e o evento pula de dia perto da meia-noite).
function parseData(s: string | null): Date | null {
  if (!s) return null;
  const t = s.trim();
  if (/^\d{9,13}$/.test(t)) {
    const n = Number(t);
    const d = new Date(n < 1e11 ? n * 1000 : n);
    return isNaN(d.getTime()) ? null : d;
  }
  const iso = t.replace(" ", "T");
  const temFuso = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  const d = new Date(temFuso ? iso : iso + "-03:00");
  return isNaN(d.getTime()) ? null : d;
}

// Duração: a plataforma pode mandar segundos, minutos ou "HH:MM:SS".
const CAMPOS_MINUTOS = ["duration_minutes", "watch_minutes", "minutes", "tempo_minutos"];

function parseDuracao(g: (p: string) => unknown): number | null {
  // Campo em minutos primeiro: se existir, o nome já diz a unidade e não
  // precisa de heurística nenhuma.
  const emMin = pick(g, ...CAMPOS_MINUTOS);
  if (emMin != null && !isNaN(Number(emMin))) return Math.round(Number(emMin) * 60);

  const bruto = pick(g, "duration", "duration_seconds", "watch_time", "time_watched",
                     "seconds", "tempo", "data.duration");
  if (!bruto) return null;
  if (/^\d+:\d{2}(:\d{2})?$/.test(bruto)) {
    const p = bruto.split(":").map(Number);
    return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  }
  const n = Number(bruto);
  return isNaN(n) ? null : Math.round(n);
}

Deno.serve(async (req) => {
  // GET responde vivo: serve pro teste de conexão que a plataforma faz ao salvar.
  if (req.method === "GET") return json({ ok: true, service: "webinar-webhook" });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  const rawText = await req.text();
  let parsed: unknown = {};
  try {
    parsed = JSON.parse(rawText);
  } catch {
    parsed = Object.fromEntries(new URLSearchParams(rawText));
  }
  // Corpo como array de 1 objeto é comum (a Payt faz isso) — desembrulha.
  const body = (Array.isArray(parsed) ? (parsed[0] ?? {}) : parsed) as Record<string, unknown>;
  const g = reader(body);

  // ── Nome do evento: URL vence payload, payload vence "não identificado" ────
  const eventoUrl = url.searchParams.get("evento");
  const eventoPayload = pick(g, "event", "event_type", "type", "action", "status",
                             "data.event", "data.type", "webhook.event");
  const eventoRaw = eventoUrl ?? eventoPayload;
  const evento = canonizar(eventoRaw ?? "");

  // ── Identificação: sem telefone OU e-mail o evento não encaixa em ninguém ──
  const telefone = onlyDigits(pick(g,
    "phone", "telefone", "whatsapp", "cellphone", "mobile", "phone_number",
    "attendee.phone", "participant.phone", "user.phone", "lead.phone",
    "subscriber.phone", "customer.phone", "data.phone", "contact.phone",
  ));
  const email = pick(g,
    "email", "e_mail", "attendee.email", "participant.email", "user.email",
    "lead.email", "subscriber.email", "customer.email", "data.email", "contact.email",
  );
  const nome = pick(g,
    "name", "nome", "full_name", "attendee.name", "participant.name", "user.name",
    "lead.name", "subscriber.name", "customer.name", "data.name", "contact.name",
  );

  const quando = parseData(pick(g,
    "timestamp", "created_at", "occurred_at", "event_time", "date", "datetime",
    "time", "data.timestamp", "data.created_at",
  )) ?? new Date();

  const aulaData = parseData(pick(g,
    "webinar_date", "session_date", "aula_data", "scheduled_at", "data.webinar_date",
  ));

  const valorBruto = pick(g, "amount", "value", "price", "total", "data.amount");
  const valorNum = valorBruto == null ? NaN : Number(valorBruto);

  const row: Record<string, unknown> = {
    evento_em: quando.toISOString(),
    evento,
    evento_raw: eventoRaw,
    telefone: telefone || null,
    email,
    nome,
    aula_data: aulaData ? aulaData.toISOString().slice(0, 10) : null,
    sala: pick(g, "webinar_id", "session_id", "room", "room_id", "sala",
               "webinar", "event_id", "data.webinar_id"),
    duracao_seg: parseDuracao(g),
    url: pick(g, "url", "link", "button_url", "cta_url", "destination", "data.url"),
    // Inteiro grande e redondo tende a ser centavos (mesma heurística do payt).
    valor: isNaN(valorNum)
      ? null
      : (Number.isInteger(valorNum) && Math.abs(valorNum) >= 1000 ? valorNum / 100 : valorNum),
    raw: body,
  };

  // Chave de dedupe: o mesmo evento, da mesma pessoa, no mesmo instante. Se a
  // plataforma mandar um id próprio, ele manda — é mais confiável que o trio.
  const idPlataforma = pick(g, "id", "event_id", "webhook_id", "data.id");
  row.dedupe_key = idPlataforma
    ? `${evento}|id:${idPlataforma}`
    : `${evento}|${telefone || (email ?? "").toLowerCase() || "?"}|${row.evento_em}`;

  const admin = createClient(SUPABASE_URL, SERVICE_KEY);
  const { error } = await admin
    .from("aula_eventos")
    .upsert(row, { onConflict: "dedupe_key", ignoreDuplicates: true });

  if (error) {
    // Loga e devolve 200 assim mesmo: derrubar o cadastro do webhook por causa
    // de uma linha custa mais que perder a linha.
    console.error("webinar-webhook: insert falhou:", error.message, "| payload:", rawText.slice(0, 2000));
    return json({ ok: true, stored: false, reason: error.message });
  }

  // Evento sem nenhuma chave é registro histórico, não operação — avisa no log
  // pra aparecer na primeira leitura, já que o painel também conta esses.
  if (!telefone && !email) {
    console.warn("webinar-webhook: evento sem telefone/e-mail:", evento, "|", rawText.slice(0, 1000));
  }
  if (!eventoUrl && !eventoPayload) {
    console.warn("webinar-webhook: sem nome de evento — cadastre com ?evento=nome:", rawText.slice(0, 1000));
  }

  return json({ ok: true, stored: true, evento, telefone: telefone || null, email });
});
