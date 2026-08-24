// =============================================================================
// supabase/functions/recuperacao-disparo/index.ts  (projeto recovery-dashboard)
// Recuperação de PIX / boleto expirado / carrinho — saindo do Make.
//
// Duas fases, chamadas pelo pg_cron de 5 em 5 minutos:
//   ?fase=agendar   -> rpc agendar_recuperacoes(): varre `recovery_events` e cria
//                      a escada de disparos de quem ainda não tem (respeitando
//                      modo <> 'off' e a trava `desde`).
//   ?fase=disparar  -> cancela quem já comprou, pega o que venceu e manda:
//                      cria/acha subscriber no ManyChat, grava p1/p2 e sendFlow.
//
// MODO (por tipo, em `recuperacao_config`) — é o que permite rodar em paralelo
// com o Make sem mandar mensagem duplicada:
//   off       nada é agendado
//   simulado  marca 'simulado' e NÃO chama o ManyChat (compara com o Make no seco)
//   teste     dispara de verdade só pros telefones de recuperacao_teste_telefones
//   ligado    dispara pra todo mundo
//
// AUTENTICAÇÃO: ?token= (RECUP_TOKEN, ou CONVITE_TOKEN como fallback).
// Secrets: MC_TOKEN (API do ManyChat) + o token acima.
// =============================================================================

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SHARED_TOKEN = Deno.env.get("RECUP_TOKEN") || Deno.env.get("CONVITE_TOKEN") || "";
const MC_TOKEN = Deno.env.get("MC_TOKEN") ?? "";

// Campos que formam o corpo de todo template aprovado da conta.
const F_P1 = 13923586;
const F_P2 = 13923587;
// Campo "whatsapp": é POR ELE que se acha um contato de WhatsApp já existente.
// A API do ManyChat não acha contato de canal WhatsApp por telefone —
// findBySystemField?phone= devolve [] mesmo com o contato lá dentro (testado
// com e sem "+", com e sem o 9, e findByName). O caminho é o mesmo que o Make
// usa: findByCustomField no campo abaixo, com o número em 55+DDD+9dígitos SEM "+".
const F_WHATSAPP = 13936072;

const MAX_POR_CHAMADA = 80;
const MAX_TENTATIVAS = 4;

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
  return { ok: r.ok && data?.status !== "error", http: r.status, data };
}

async function subscriberId(wa: string, nome: string): Promise<string> {
  // 1) já existe? O campo `whatsapp` é a única chave que a API aceita pra
  //    contato de WhatsApp (ver F_WHATSAPP). Formato: 55DDD9XXXXXXXX, sem "+".
  const achado = await mc("GET", "/fb/subscriber/findByCustomField", {
    field_id: F_WHATSAPP, field_value: wa,
  });
  const lista = (achado.data?.data as Array<Record<string, unknown>> | undefined) ?? [];
  if (achado.ok && lista.length > 0 && lista[0]?.id) return String(lista[0].id);

  // 2) não existe: cria e CARIMBA o campo, senão o contato nasce invisível pro
  //    passo 1 e a próxima mensagem pra essa pessoa volta a falhar.
  const partes = (nome ?? "").trim().split(/\s+/);
  const criado = await mc("POST", "/fb/subscriber/createSubscriber", {
    whatsapp_phone: "+" + wa,
    first_name: partes[0] ?? "",
    last_name: partes.slice(1).join(" "),
    has_opt_in: true,
    consent_phrase: "Recuperacao de compra (Payt)",
  });
  const idCriado = (criado.data?.data as Record<string, unknown> | undefined)?.id;
  if (criado.ok && idCriado) {
    await mc("POST", "/fb/subscriber/setCustomField", {
      subscriber_id: String(idCriado), field_id: F_WHATSAPP, field_value: wa,
    });
    return String(idCriado);
  }

  // 3) createSubscriber dizendo "already exists" com o passo 1 vazio = contato
  //    antigo, de antes do carimbo. Segunda busca cobre corrida entre crons.
  const retry = await mc("GET", "/fb/subscriber/findByCustomField", {
    field_id: F_WHATSAPP, field_value: wa,
  });
  const lista2 = (retry.data?.data as Array<Record<string, unknown>> | undefined) ?? [];
  if (retry.ok && lista2.length > 0 && lista2[0]?.id) return String(lista2[0].id);

  throw new Error(
    `createSubscriber(${criado.http}): ${JSON.stringify(criado.data).slice(0, 300)} | ` +
    `findByCustomField(${achado.http}): ${JSON.stringify(achado.data).slice(0, 200)}`,
  );
}

// {nome} e {valor} viram os dados do evento; o texto final vai pros campos que
// os templates aprovados usam como corpo.
function render(texto: string | null, nome: string | null, valor: number | null): string {
  const v = valor == null ? "" : Number(valor).toFixed(2).replace(".", ",");
  return (texto ?? "")
    .replaceAll("{nome}", (nome ?? "").trim().split(/\s+/)[0] ?? "")
    .replaceAll("{valor}", v);
}

type Linha = {
  disparo_id: number; tipo: string; etapa: string; modo: string;
  flow_ns: string | null; texto_p1: string | null; texto_p2: string | null;
  telefone: string | null; telefone_core: string; nome: string | null;
  valor: number | null; eh_teste: boolean; tentativas: number;
};

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") ?? req.headers.get("x-token") ?? "";
  if (!SHARED_TOKEN || token !== SHARED_TOKEN) return json({ error: "unauthorized" }, 401);

  const fase = (url.searchParams.get("fase") ?? "").trim().toLowerCase();
  const admin = createClient(SUPABASE_URL, SERVICE_KEY);

  // ── FASE 1: agendar a escada dos eventos novos ─────────────────────────────
  if (fase === "agendar") {
    const { data, error } = await admin.rpc("agendar_recuperacoes", { p_limite: 500 });
    if (error) { console.error("agendar:", error.message); return json({ error: error.message }, 500); }
    console.log(`recuperacao agendar: ${data} disparos criados`);
    return json({ ok: true, fase, agendados: data });
  }

  if (fase !== "disparar") return json({ error: "fase inválida (agendar|disparar)" }, 400);

  // ── FASE 2: drenar o que venceu ────────────────────────────────────────────
  // Supressão primeiro: quem comprou depois do evento sai da fila (o que o
  // Search Rows/comprador-check fazia no Make).
  const { data: cancelados, error: cErr } = await admin.rpc("cancelar_recuperacoes_compradas");
  if (cErr) console.error("cancelar_recuperacoes_compradas:", cErr.message);

  const { data: fila, error: fErr } = await admin.rpc("fila_recuperacao", {
    p_limite: MAX_POR_CHAMADA, p_max_tentativas: MAX_TENTATIVAS,
  });
  if (fErr) { console.error("fila_recuperacao:", fErr.message); return json({ error: fErr.message }, 500); }

  let enviados = 0, simulados = 0, falhas = 0;

  for (const l of (fila ?? []) as Linha[]) {
    const p1 = render(l.texto_p1, l.nome, l.valor);
    const p2 = render(l.texto_p2, l.nome, l.valor);
    const upd: Record<string, unknown> = {
      tentativas: (l.tentativas ?? 0) + 1,
      preview: [p1, p2].filter(Boolean).join("\n\n"),
    };

    // Quem NÃO dispara de verdade: modo simulado, ou modo teste e o telefone não
    // está na whitelist. Fica registrado como 'simulado' pra comparar com o Make.
    const soSimula = l.modo === "simulado" || (l.modo === "teste" && !l.eh_teste);
    if (soSimula) {
      Object.assign(upd, {
        status: "simulado", erro: null,
        motivo: l.modo === "simulado" ? "modo simulado" : "fora da lista de teste",
        enviado_em: new Date().toISOString(),
      });
      await admin.from("recuperacao_disparos").update(upd).eq("id", l.disparo_id);
      simulados++;
      continue;
    }

    try {
      if (!MC_TOKEN) throw new Error("MC_TOKEN não configurado");
      if (!l.flow_ns) throw new Error(`etapa ${l.tipo}/${l.etapa} sem flow_ns`);
      const wa = waPhone(l.telefone ?? "");
      if (!wa) throw new Error("telefone inválido pra WhatsApp");

      const sid = await subscriberId(wa, l.nome ?? "");

      for (const [fieldId, texto] of [[F_P1, p1], [F_P2, p2]] as const) {
        if (!texto) continue;
        const r = await mc("POST", "/fb/subscriber/setCustomField", {
          subscriber_id: sid, field_id: fieldId, field_value: texto,
        });
        if (!r.ok) throw new Error(`setCustomField(${r.http}): ${JSON.stringify(r.data).slice(0, 200)}`);
      }

      const envio = await mc("POST", "/fb/sending/sendFlow", { subscriber_id: sid, flow_ns: l.flow_ns });
      if (!envio.ok) throw new Error(`sendFlow(${envio.http}): ${JSON.stringify(envio.data).slice(0, 300)}`);

      Object.assign(upd, {
        status: "enviado", erro: null, mc_subscriber_id: sid,
        enviado_em: new Date().toISOString(),
      });
      enviados++;
    } catch (e) {
      // Erro não é ponto final enquanto houver tentativa: volta pra fila com
      // espera crescente (10, 20, 30 min). `status='erro'` passa a significar
      // "desisti depois de MAX_TENTATIVAS", que é o que o painel deve mostrar.
      const tentativas = (l.tentativas ?? 0) + 1;
      const desiste = tentativas >= MAX_TENTATIVAS;
      Object.assign(upd, {
        status: desiste ? "erro" : "agendado",
        erro: String(e).slice(0, 500),
        ...(desiste ? {} : {
          quando_enviar: new Date(Date.now() + tentativas * 10 * 60_000).toISOString(),
        }),
      });
      falhas++;
      console.error(`recuperacao disparo=${l.disparo_id} (${l.tipo}/${l.etapa}):`, String(e).slice(0, 400));
    }

    await admin.from("recuperacao_disparos").update(upd).eq("id", l.disparo_id);
    await new Promise((r) => setTimeout(r, 150)); // rate limit do ManyChat
  }

  const filaCheia = ((fila ?? []) as unknown[]).length === MAX_POR_CHAMADA;
  console.log(
    `recuperacao disparar: ${enviados} enviados, ${simulados} simulados, ${falhas} falhas, ` +
    `${cancelados ?? 0} cancelados por compra` + (filaCheia ? " (fila cheia)" : ""),
  );
  return json({
    ok: true, fase, enviados, simulados, falhas,
    cancelados_por_compra: cancelados ?? 0, fila_cheia: filaCheia,
  });
});
