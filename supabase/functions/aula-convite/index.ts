// =============================================================================
// supabase/functions/aula-convite/index.ts  (projeto recovery-dashboard)
// Convite pra AULA aos 7 dias de compra (Posições Secretas) — SEM Make.
//
// Três fases, chamadas pelo pg_cron (fuso Brasília):
//   ?fase=selecionar (08h30) -> rpc selecionar_convites_aula(): grava a base do
//                               dia em `convites_aula` (regra dos 7 dias, dedupe
//                               por telefone_core, cutoff/trava na config).
//   ?fase=disparar   (09h00) -> pra cada linha status='selecionada': cria/acha o
//                               subscriber no ManyChat, grava o custom field
//                               `link_sala` (Applive pré-preenchido) e dispara o
//                               fluxo do "é hoje" (sendFlow). Marca 'enviada' só
//                               com OK e registra a etapa `e_hoje` em envios.
//   ?fase=etapa&etapa=X       -> dispara UMA das outras mensagens do dia pra quem
//                               recebeu o convite hoje. Hora e fluxo de cada
//                               etapa vivem em `convites_aula_etapas` (0006):
//                                 18h30 falta_1h | 19h15 ao_vivo | 19h30 comecamos
//
// Por que por fora: o Smart Delay do ManyChat é sempre relativo a quando a pessoa
// entrou no passo, então "17h30" virava "+150min depois do clique". Com o cron
// cada mensagem cai na hora cravada, independente de quando a pessoa entrou ou
// clicou. Quem tocou BLOQUEAR é barrado dentro do fluxo do ManyChat (condição
// clicou_aula = 'bloqueou' na entrada), que é onde esse campo vive.
//
// A fase de disparo processa no máx. MAX_POR_CHAMADA por invocação (limite de
// tempo da edge function + rate limit do ManyChat ~10 req/s). O cron chama a
// fase algumas vezes seguidas (12:00/12:05/12:10/12:15 UTC) até drenar a fila —
// quem sobra ou falha continua 'selecionada'/'erro' e entra na chamada seguinte.
//
// AUTENTICAÇÃO: ?token=CONVITE_TOKEN (mesmo padrão do payt-webhook).
// Secrets: CONVITE_TOKEN, MC_TOKEN (API do ManyChat), MC_FLOW_NS (fallback do
// fluxo do "é hoje" quando a etapa e_hoje ainda não tem flow_ns no banco).
// =============================================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SHARED_TOKEN = Deno.env.get("CONVITE_TOKEN") ?? "";
const MC_TOKEN = Deno.env.get("MC_TOKEN") ?? "";
const MC_FLOW_NS = Deno.env.get("MC_FLOW_NS") ?? "";
const MC_LINK_FIELD = Deno.env.get("MC_LINK_FIELD") ?? "link_sala";

// Campos que formam o corpo de TODO template aprovado da conta.
const F_P1 = 13923586;
const F_P2 = 13923587;

const LINK_BASE = "https://luizavitoria.applive.com.br/mulher-inesquecivel-v2/lp";
const MAX_POR_CHAMADA = 80;   // por invocação; o cron invoca em sequência até drenar
const MAX_TENTATIVAS = 4;     // depois disso a linha fica em 'erro' e para de tentar

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// WhatsApp E.164 BR: 55 + DDD + 9 dígitos (adiciona o 9 se faltar).
function waPhone(tel: string): string {
  let d = (tel ?? "").replace(/\D/g, "");
  if (d.length >= 12 && d.startsWith("55")) d = d.slice(2);
  if (d.length === 10) d = d.slice(0, 2) + "9" + d.slice(2);
  return d.length === 11 ? "55" + d : "";
}

function hojeBrasilia(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/Sao_Paulo" });
}

// Chamada à API do ManyChat. status==="error" no corpo também conta como falha.
async function mc(method: "GET" | "POST", path: string, payload?: Record<string, unknown>) {
  const url = new URL("https://api.manychat.com" + path);
  const init: RequestInit = {
    method,
    headers: { Authorization: `Bearer ${MC_TOKEN}`, "Content-Type": "application/json" },
  };
  if (method === "GET" && payload) {
    for (const [k, v] of Object.entries(payload)) url.searchParams.set(k, String(v));
  } else if (payload) {
    init.body = JSON.stringify(payload);
  }
  const r = await fetch(url, init);
  const data = (await r.json().catch(() => ({}))) as Record<string, unknown>;
  const ok = r.ok && data?.status !== "error";
  return { ok, http: r.status, data };
}

// Cria o subscriber; se já existir, acha pelo telefone. Devolve o id ou lança.
async function subscriberId(wa: string, nome: string): Promise<string> {
  const partes = (nome ?? "").trim().split(/\s+/);
  const criado = await mc("POST", "/fb/subscriber/createSubscriber", {
    whatsapp_phone: "+" + wa,
    first_name: partes[0] ?? "",
    last_name: partes.slice(1).join(" "),
    has_opt_in: true,
    consent_phrase: "Compradora Posicoes Secretas (Payt)",
  });
  const idCriado = (criado.data?.data as Record<string, unknown> | undefined)?.id;
  if (criado.ok && idCriado) return String(idCriado);

  // Provável duplicado — busca pelo telefone.
  const achado = await mc("GET", "/fb/subscriber/findBySystemField", { phone: "+" + wa });
  const idAchado = (achado.data?.data as Record<string, unknown> | undefined)?.id;
  if (achado.ok && idAchado) return String(idAchado);

  throw new Error(
    `createSubscriber(${criado.http}): ${JSON.stringify(criado.data).slice(0, 300)} | ` +
    `find(${achado.http}): ${JSON.stringify(achado.data).slice(0, 200)}`,
  );
}

type EtapaCfg = {
  etapa: string;
  flow_ns: string | null;
  ativo: boolean;
  descricao: string | null;
  texto_p1: string | null;
  texto_p2: string | null;
};

// Config de uma etapa (hora, fluxo e copy vivem no banco, não no código).
async function etapaConfig(
  admin: ReturnType<typeof createClient>,
  etapa: string,
): Promise<EtapaCfg | null> {
  const { data } = await admin
    .from("convites_aula_etapas")
    .select("etapa, flow_ns, ativo, descricao, texto_p1, texto_p2")
    .eq("etapa", etapa)
    .maybeSingle();
  return (data as EtapaCfg) ?? null;
}

// Escreve a copy da etapa nos campos que os templates aprovados usam como corpo
// ({{cuf_13923586}} / {{cuf_13923587}}). É o que faz a mensagem chegar como
// TEMPLATE — ou seja, mesmo com a janela de 24h do WhatsApp fechada.
async function gravarCopy(cfg: EtapaCfg, sid: string, link: string | null) {
  const troca = (t: string | null) => (t ?? "").replaceAll("{link}", link ?? "");
  for (const [fieldId, texto] of [[F_P1, cfg.texto_p1], [F_P2, cfg.texto_p2]] as const) {
    if (texto == null) continue;
    const r = await mc("POST", "/fb/subscriber/setCustomField", {
      subscriber_id: sid, field_id: fieldId, field_value: troca(texto),
    });
    if (!r.ok) throw new Error(`setCustomField(p${fieldId === F_P1 ? 1 : 2}, ${r.http}): ${JSON.stringify(r.data).slice(0, 200)}`);
  }
}

// 1 linha por (convidada, etapa, dia). 'enviada' nunca repete; 'erro' volta na
// próxima chamada do cron até MAX_TENTATIVAS.
async function registrarEnvio(
  admin: ReturnType<typeof createClient>,
  conviteId: number,
  etapa: string,
  aulaData: string,
  tentativas: number,
  erro: string | null,
) {
  await admin.from("convites_aula_envios").upsert({
    convite_id: conviteId,
    etapa,
    aula_data: aulaData,
    status: erro ? "erro" : "enviada",
    tentativas,
    erro: erro ? erro.slice(0, 500) : null,
    enviada_em: erro ? null : new Date().toISOString(),
  }, { onConflict: "convite_id,etapa,aula_data" });
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  const fase = (url.searchParams.get("fase") ?? "").trim().toLowerCase();
  const admin = createClient(SUPABASE_URL, SERVICE_KEY);

  // ── FASE 1: seleção da base do dia (toda a regra vive no SQL) ──────────────
  if (fase === "selecionar") {
    const { data, error } = await admin.rpc("selecionar_convites_aula");
    if (error) { console.error("selecionar:", error.message); return json({ error: error.message }, 500); }
    console.log(`aula-convite selecionar: ${data} novas na base`);
    return json({ ok: true, fase, selecionadas: data });
  }

  // ── FASE 3: uma mensagem da cadência do dia (falta_1h | ao_vivo | comecamos) ─
  if (fase === "etapa") {
    const etapa = (url.searchParams.get("etapa") ?? "").trim().toLowerCase();
    if (!etapa) return json({ error: "faltou ?etapa=" }, 400);
    if (!MC_TOKEN) return json({ error: "MC_TOKEN não configurado — nada disparado" }, 400);

    const cfg = await etapaConfig(admin, etapa);
    if (!cfg) return json({ error: `etapa desconhecida: ${etapa}` }, 400);
    if (!cfg.ativo) { console.log(`aula-convite etapa=${etapa}: desligada, nada a fazer`); return json({ ok: true, fase, etapa, desligada: true }); }
    if (!cfg.flow_ns) return json({ error: `etapa ${etapa} sem flow_ns no banco — nada disparado` }, 400);

    const { data: fila, error: fErr } = await admin.rpc("fila_convites_etapa", {
      p_etapa: etapa, p_limite: MAX_POR_CHAMADA, p_max_tentativas: MAX_TENTATIVAS,
    });
    if (fErr) { console.error(`etapa ${etapa}:`, fErr.message); return json({ error: fErr.message }, 500); }

    const dia = hojeBrasilia();
    let enviadas = 0, falhas = 0;

    for (const linha of (fila ?? []) as Array<{ convite_id: number; mc_subscriber_id: string; link_sala: string | null; tentativas: number }>) {
      const tentativas = (linha.tentativas ?? 0) + 1;
      try {
        await gravarCopy(cfg, linha.mc_subscriber_id, linha.link_sala);
        const envio = await mc("POST", "/fb/sending/sendFlow", {
          subscriber_id: linha.mc_subscriber_id, flow_ns: cfg.flow_ns,
        });
        if (!envio.ok) throw new Error(`sendFlow(${envio.http}): ${JSON.stringify(envio.data).slice(0, 300)}`);
        await registrarEnvio(admin, linha.convite_id, etapa, dia, tentativas, null);
        enviadas++;
      } catch (e) {
        await registrarEnvio(admin, linha.convite_id, etapa, dia, tentativas, String(e));
        falhas++;
        console.error(`aula-convite etapa=${etapa} convite=${linha.convite_id}:`, String(e).slice(0, 500));
      }
      await new Promise((r) => setTimeout(r, 150)); // rate limit do ManyChat
    }

    const filaCheia = ((fila ?? []) as unknown[]).length === MAX_POR_CHAMADA;
    console.log(`aula-convite etapa=${etapa}: ${enviadas} enviadas, ${falhas} falhas` +
      (filaCheia ? " (fila pode ter mais — próxima chamada do cron drena)" : ""));
    return json({ ok: true, fase, etapa, enviadas, falhas, fila_cheia: filaCheia });
  }

  if (fase !== "disparar") return json({ error: "fase inválida (selecionar|disparar|etapa)" }, 400);

  // ── FASE 2: convite do dia ("é hoje") via ManyChat ─────────────────────────
  if (!MC_TOKEN) return json({ error: "MC_TOKEN não configurado — nada disparado" }, 400);

  const cfgHoje = await etapaConfig(admin, "e_hoje");
  const flowHoje = cfgHoje?.flow_ns || MC_FLOW_NS;
  if (!flowHoje) {
    return json({ error: "sem fluxo pro 'é hoje' (convites_aula_etapas.flow_ns nem MC_FLOW_NS)" }, 400);
  }
  if (cfgHoje && !cfgHoje.ativo) {
    console.log("aula-convite disparar: etapa e_hoje desligada, nada a fazer");
    return json({ ok: true, fase, desligada: true });
  }

  const { data: fila, error: qErr } = await admin
    .from("convites_aula")
    .select("id, telefone, nome, email, tentativas, status")
    .in("status", ["selecionada", "erro"])
    .lt("tentativas", MAX_TENTATIVAS)
    .order("selecionada_em", { ascending: true })
    .limit(MAX_POR_CHAMADA);
  if (qErr) return json({ error: qErr.message }, 500);

  const aulaData = hojeBrasilia();
  let enviadas = 0, falhas = 0;

  for (const c of fila ?? []) {
    const wa = waPhone(c.telefone);
    const upd: Record<string, unknown> = { tentativas: (c.tentativas ?? 0) + 1 };
    try {
      if (!wa) throw new Error("telefone inválido pra WhatsApp");
      const link =
        `${LINK_BASE}?nome=${encodeURIComponent(c.nome ?? "")}` +
        `&email=${encodeURIComponent(c.email ?? "")}` +
        `&telefone=${encodeURIComponent(wa)}`;

      const sid = await subscriberId(wa, c.nome ?? "");

      const campo = await mc("POST", "/fb/subscriber/setCustomFieldByName", {
        subscriber_id: sid, field_name: MC_LINK_FIELD, field_value: link,
      });
      if (!campo.ok) throw new Error(`setCustomField(${campo.http}): ${JSON.stringify(campo.data).slice(0, 300)}`);

      if (cfgHoje) await gravarCopy(cfgHoje, sid, link);

      const envio = await mc("POST", "/fb/sending/sendFlow", {
        subscriber_id: sid, flow_ns: flowHoje,
      });
      if (!envio.ok) throw new Error(`sendFlow(${envio.http}): ${JSON.stringify(envio.data).slice(0, 300)}`);

      Object.assign(upd, {
        status: "enviada", erro: null, mc_subscriber_id: sid, link_sala: link,
        aula_data: aulaData, enviada_em: new Date().toISOString(),
      });
      await registrarEnvio(admin, c.id, "e_hoje", aulaData, (c.tentativas ?? 0) + 1, null);
      enviadas++;
    } catch (e) {
      Object.assign(upd, { status: "erro", erro: String(e).slice(0, 500) });
      falhas++;
      console.error(`aula-convite disparar id=${c.id}:`, String(e).slice(0, 500));
    }
    await admin.from("convites_aula").update(upd).eq("id", c.id);
    await new Promise((r) => setTimeout(r, 150)); // respeita o rate limit do ManyChat
  }

  const restantes = (fila?.length ?? 0) === MAX_POR_CHAMADA;
  console.log(`aula-convite disparar: ${enviadas} enviadas, ${falhas} falhas` +
    (restantes ? " (fila pode ter mais — próxima chamada do cron drena)" : ""));
  return json({ ok: true, fase, enviadas, falhas, fila_cheia: restantes });
});
