/**
 * recovery-flow-tracker — Cloudflare Worker
 * =============================================================================
 * Registra os eventos do funil de cada FLUXO do ManyChat (pix/boleto gerado,
 * pix/boleto expirado, carrinho abandonado, boas-vindas, disparo_venda) e grava
 * UMA linha na tabela `manychat_eventos` do Postgres (Supabase) via PostgREST.
 *
 * (Até 2026-08-12 gravava na aba `eventos_manychat` do Google Sheets; a
 * planilha foi aposentada como intermediária — o dashboard lê do Postgres.)
 *
 * Funil clássico (3 etapas), por fluxo:
 *   recebeu  → a pessoa recebeu o fluxo
 *   entrou   → clicou no botão de entrada
 *   engajou  → clicou no conteúdo / avançou no fluxo
 *
 * Funil do disparo de venda (fluxo `disparo_venda`), com bifurcação:
 *   recebeu → clicou → [calculando | sentindo] → {braço}_respondeu
 *     → {braço}_pitch_1 → {braço}_pitch_2 → {braço}_pitch_3
 *
 * Cada etapa é um tijolo "External Request (POST)" no fluxo do ManyChat:
 *   POST https://<worker>/event?token=SECRET&fluxo=<slug>&etapa=<etapa>
 *   body: Full Contact Data → traz { phone, id } (1 clique, sem montar JSON)
 *
 * `fluxo` e `etapa` vão na QUERY (caminho fácil no ManyChat); o corpo fica só
 * com phone/id. Copie o mesmo bloco entre etapas trocando só o &etapa=, e entre
 * fluxos trocando só o &fluxo=.
 *
 * Resposta rápida + escrita em background: o Worker responde 200 pro
 * ManyChat assim que valida o payload, ANTES de escrever no banco. A escrita
 * roda em `ctx.waitUntil` com retry/backoff. Isso garante que uma falha/
 * lentidão do banco NUNCA trava a automação do ManyChat.
 *
 * Secrets / vars (wrangler secret put / [vars] no wrangler.toml):
 *   SB_URL          — url do projeto Supabase (https://<ref>.supabase.co)
 *   SB_SERVICE_KEY  — service_role key (grava direto, ignora RLS)
 *   SHARED_TOKEN    — segredo arbitrário; o ManyChat manda ?token=... igual
 *   TABLE_NAME      — opcional, default "manychat_eventos"
 * =============================================================================
 */

// Etapas do funil (recebeu→entrou→engajou), iguais pros 4 fluxos da Luiza.
// `fluxo` é livre (uma automação por fluxo); só validamos a etapa pra um typo
// não furar o funil.
//
// O fluxo `disparo_venda` (disparo via API pra venda de produto) tem um funil
// próprio, com bifurcação depois do clique:
//   recebeu → clicou → [calculando | sentindo] → {braço}_respondeu
//     → {braço}_pitch_1 → {braço}_pitch_2 → {braço}_pitch_3
const VALID_ETAPAS = new Set([
  'recebeu',
  'entrou',
  'engajou',
  // funil disparo_venda
  'clicou',
  'calculando',
  'sentindo',
  'calculando_respondeu',
  'calculando_pitch_1',
  'calculando_pitch_2',
  'calculando_pitch_3',
  'sentindo_respondeu',
  'sentindo_pitch_1',
  'sentindo_pitch_2',
  'sentindo_pitch_3',
]);

export default {
  async fetch(request, env, ctx) {
    if (request.method === 'GET') {
      return json({ ok: true, service: 'recovery-flow-tracker', sink: 'supabase' });
    }
    if (request.method !== 'POST') {
      return json({ error: 'method not allowed' }, 405);
    }

    const url = new URL(request.url);
    const token = url.searchParams.get('token') || request.headers.get('x-token') || '';
    if (!env.SHARED_TOKEN || token !== env.SHARED_TOKEN) {
      return json({ error: 'unauthorized' }, 401);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: 'invalid json' }, 400);
    }

    // Rota separada: a venda que nao passa pelo nosso webhook (ver registrarCompra).
    if (url.pathname.replace(/\/+$/, '').endsWith('/compra')) {
      return registrarCompra(url, body, env, ctx);
    }

    // fluxo e etapa vêm na query; o corpo é só o Full Contact Data (phone/id).
    const fluxo = String(url.searchParams.get('fluxo') || body.fluxo || '')
      .trim()
      .toLowerCase();
    const etapa = String(url.searchParams.get('etapa') || body.etapa || '')
      .trim()
      .toLowerCase();
    const telefone = onlyDigits(body.telefone || body.phone || body.whatsapp_phone || '');
    const subscriberId = String(body.subscriber_id || body.user_id || body.id || '').trim();

    if (!fluxo) {
      return json({ error: 'fluxo obrigatório (?fluxo=...)' }, 400);
    }
    if (!VALID_ETAPAS.has(etapa)) {
      return json({ error: `etapa inválida: '${etapa}'`, validas: [...VALID_ETAPAS] }, 400);
    }
    if (!telefone && !subscriberId) {
      return json({ error: 'telefone ou subscriber_id obrigatório' }, 400);
    }

    const ts = manausIso(new Date());

    // Responde 200 pro ManyChat IMEDIATAMENTE — a automação nunca deve travar
    // por causa do rastreio. A escrita no banco (com retry) roda em background
    // via waitUntil, fora do request/response.
    const row = {
      evento_em: ts,
      telefone: telefone || null,
      subscriber_id: subscriberId || null,
      fluxo,
      etapa,
    };
    ctx.waitUntil(
      insertRowWithRetry(env, row).catch((err) => {
        console.error('insert failed (background):', err && err.stack ? err.stack : String(err));
      }),
    );

    return json({ ok: true, fluxo, etapa, ts, queued: true });
  },
};

// ── /compra — a venda que chega pelo fluxo, não pelo webhook ─────────────────
/**
 * O Protocolo do Prazer vende numa oferta da Payt que não tem a URL do
 * `payt-webhook` cadastrada, então essa venda nunca aparece na tabela
 * `compras` — o painel não vê, e o tipo `compra_protocolo` do motor nunca
 * dispara. Quem sabe da venda é o fluxo do ManyChat em que a pessoa cai.
 *
 * Então o fluxo avisa: um External Request na entrada grava a compra aqui.
 *
 * O que essa rota NÃO faz: substituir o webhook. O dado que o fluxo tem é o
 * contato (nome, telefone, e-mail) — não tem transação, UTM nem order bump, e
 * o preço só existe porque vem cravado na query. E, como é o Make que joga a
 * pessoa no fluxo, pausar o cenário faz esta rota parar junto. É registro de
 * venda, não migração de gatilho.
 *
 *   POST /compra?token=SECRET&produto=Protocolo+do+Prazer&valor=97
 *   body: Full Contact Data (o mesmo do rastreio — phone, id, name, email)
 *
 * Dedupe: `transaction_id` sintético `mc-<produto>-<contato>-<dia>`, então a
 * mesma pessoa reentrando no fluxo no mesmo dia não vira duas vendas (o que
 * inflaria a conversão). A origem fica gravada em `raw`, pra nunca confundir
 * uma linha dessas com uma que veio da Payt.
 */
async function registrarCompra(url, body, env, ctx) {
  const produto = String(url.searchParams.get('produto') || '').trim();
  if (!produto) {
    return json({ error: 'produto obrigatorio (?produto=...)' }, 400);
  }
  const valorParam = url.searchParams.get('valor');
  const valor = valorParam != null && valorParam !== '' && !isNaN(Number(valorParam))
    ? Number(valorParam)
    : null;

  const telefone = onlyDigits(body.telefone || body.phone || body.whatsapp_phone || '');
  const subscriberId = String(body.subscriber_id || body.user_id || body.id || '').trim();
  if (!telefone && !subscriberId) {
    return json({ error: 'telefone ou subscriber_id obrigatorio' }, 400);
  }

  const nome = String(
    body.nome || body.name ||
    [body.first_name, body.last_name].filter(Boolean).join(' ') || '',
  ).trim() || null;
  const email = String(body.email || '').trim() || null;

  const agora = manausIso(new Date());
  const row = {
    compra_em: agora,
    nome,
    email,
    telefone: telefone || null,
    valor,
    produto,
    transaction_id: `mc-${slug(produto)}-${subscriberId || telefone}-${agora.slice(0, 10)}`,
    raw: {
      origem: 'manychat',
      fluxo: url.searchParams.get('fluxo') || null,
      subscriber_id: subscriberId || null,
      recebido_em: agora,
    },
  };

  // Mesma regra do rastreio: responde ja, escreve em background. Uma lentidao
  // do banco nao pode segurar a automacao do ManyChat.
  ctx.waitUntil(
    insertRowWithRetry(env, row, 'compras', true).catch((err) => {
      console.error('compra insert failed (background):', err && err.stack ? err.stack : String(err));
    }),
  );

  return json({ ok: true, destino: 'compras', produto, telefone, valor, queued: true });
}

function slug(v) {
  return String(v || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    .slice(0, 40);
}

// ── Supabase PostgREST insert (com retry pra absorver instabilidade) ─────────

const MAX_RETRIES = 5;
const BASE_DELAY_MS = 600;

async function insertRowWithRetry(env, row, table, ignoreDuplicates) {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      await insertRow(env, row, table, ignoreDuplicates);
      return;
    } catch (err) {
      const retryable = err && (err.status === 429 || err.status >= 500);
      if (!retryable || attempt === MAX_RETRIES) throw err;
      const delay = BASE_DELAY_MS * 2 ** attempt + Math.random() * 300;
      await sleep(delay);
    }
  }
}

async function insertRow(env, row, tabela, ignoreDuplicates) {
  const table = tabela || env.TABLE_NAME || 'manychat_eventos';
  // Com dedupe: o PostgREST precisa do on_conflict na URL E do resolution no
  // Prefer — so um dos dois devolve 409 em vez de ignorar a repeticao.
  const qs = ignoreDuplicates ? '?on_conflict=transaction_id' : '';
  const prefer = ignoreDuplicates
    ? 'return=minimal,resolution=ignore-duplicates'
    : 'return=minimal';
  const resp = await fetch(`${env.SB_URL}/rest/v1/${table}${qs}`, {
    method: 'POST',
    headers: {
      apikey: env.SB_SERVICE_KEY,
      authorization: `Bearer ${env.SB_SERVICE_KEY}`,
      'content-type': 'application/json',
      prefer,
    },
    body: JSON.stringify(row),
  });

  if (!resp.ok) {
    const err = new Error(`postgrest ${resp.status}: ${await resp.text()}`);
    err.status = resp.status;
    throw err;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── helpers ──────────────────────────────────────────────────────────────────

function onlyDigits(v) {
  return String(v || '').replace(/\D/g, '');
}

/** ISO 8601 no fuso America/Manaus (UTC-4 fixo). Ex: 2026-06-22T09:15:03-04:00 */
function manausIso(date) {
  const m = new Date(date.getTime() - 4 * 3600 * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return (
    `${m.getUTCFullYear()}-${p(m.getUTCMonth() + 1)}-${p(m.getUTCDate())}` +
    `T${p(m.getUTCHours())}:${p(m.getUTCMinutes())}:${p(m.getUTCSeconds())}-04:00`
  );
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
