/**
 * recovery-flow-tracker — Cloudflare Worker
 * =============================================================================
 * Registra os eventos do funil de cada FLUXO do ManyChat (pix/boleto gerado,
 * pix/boleto expirado, carrinho abandonado, boas-vindas) e grava UMA linha na
 * aba `eventos_manychat` da planilha do dashboard.
 *
 * Funil medido (3 etapas), por fluxo:
 *   recebeu  → a pessoa recebeu o fluxo
 *   entrou   → clicou no botão de entrada
 *   engajou  → clicou no conteúdo / avançou no fluxo
 *
 * Cada etapa é um tijolo "External Request (POST)" no fluxo do ManyChat:
 *   POST https://<worker>/event?token=SECRET&fluxo=<slug>&etapa=<recebeu|entrou|engajou>
 *   body: Full Contact Data → traz { phone, id } (1 clique, sem montar JSON)
 *     └─ Worker → Google Sheets API (values:append) → aba eventos_manychat
 *
 * `fluxo` e `etapa` vão na QUERY (caminho fácil no ManyChat); o corpo fica só
 * com phone/id. Copie o mesmo bloco entre etapas trocando só o &etapa=, e entre
 * fluxos trocando só o &fluxo=.
 *
 * Auth Google: service account (JWT RS256 → access token). É o MESMO service
 * account do dashboard (service_account.json) — a planilha já está
 * compartilhada com ele como Editor (mesma planilha de cliques_manychat).
 *
 * Resposta rápida + escrita em background: o Worker responde 200 pro
 * ManyChat assim que valida o payload, ANTES de escrever no Sheets. A escrita
 * roda em `ctx.waitUntil` com retry/backoff em caso de 429 (cota de escrita
 * do Sheets API é global por service account — compartilhada com outros
 * Workers). Isso garante que uma falha/lentidão do Sheets NUNCA trava a
 * automação do ManyChat.
 *
 * Secrets / vars (wrangler secret put / [vars] no wrangler.toml):
 *   SHEET_ID         — id da planilha (config.SPREADSHEET_ID do dashboard)
 *   SA_EMAIL         — client_email do service account
 *   SA_PRIVATE_KEY   — private_key do service account (PEM, com \n reais)
 *   SHARED_TOKEN     — segredo arbitrário; o ManyChat manda ?token=... igual
 *   TAB_NAME         — opcional, default "eventos_manychat"
 * =============================================================================
 */

const TOKEN_URL = 'https://oauth2.googleapis.com/token';
const SCOPE = 'https://www.googleapis.com/auth/spreadsheets';

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
      return json({ ok: true, service: 'recovery-flow-tracker' });
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
    // por causa do rastreio. A escrita no Sheets (com retry em caso de 429 de
    // cota) roda em background via waitUntil, fora do request/response.
    ctx.waitUntil(
      appendRowWithRetry(env, [ts, telefone, subscriberId, fluxo, etapa]).catch((err) => {
        console.error('append failed (background):', err && err.stack ? err.stack : String(err));
      }),
    );

    return json({ ok: true, fluxo, etapa, ts, queued: true });
  },
};

// ── Google Sheets append (com retry pra absorver picos de tráfego) ───────────

// A cota de escrita do Sheets API (60/min) é GLOBAL por service account —
// compartilhada com outros Workers (manychat-click-tracker, edital-flow-
// tracker). Um fluxo de alto volume (ex: "recebeu" disparando em toda
// mensagem) pode estourar isso sozinho. Retry com backoff absorve o pico sem
// perder o evento nem travar quem está chamando.
const MAX_RETRIES = 5;
const BASE_DELAY_MS = 600;

async function appendRowWithRetry(env, row) {
  let accessToken = await getAccessToken(env);
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      await appendRow(env, accessToken, row);
      return;
    } catch (err) {
      const retryable = err && (err.status === 429 || err.status >= 500);
      if (!retryable || attempt === MAX_RETRIES) throw err;
      // token expirado/inválido no meio dos retries — renova.
      if (err.status === 401) accessToken = await getAccessToken(env);
      const delay = BASE_DELAY_MS * 2 ** attempt + Math.random() * 300;
      await sleep(delay);
    }
  }
}

async function appendRow(env, accessToken, row) {
  const tab = env.TAB_NAME || 'eventos_manychat';
  const range = encodeURIComponent(`${tab}!A:E`);
  const endpoint =
    `https://sheets.googleapis.com/v4/spreadsheets/${env.SHEET_ID}` +
    `/values/${range}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`;

  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${accessToken}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify({ values: [row] }),
  });

  if (!resp.ok) {
    const err = new Error(`sheets ${resp.status}: ${await resp.text()}`);
    err.status = resp.status;
    throw err;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── OAuth: service account JWT (RS256) → access token ────────────────────────

async function getAccessToken(env) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', typ: 'JWT' };
  const claim = {
    iss: env.SA_EMAIL,
    scope: SCOPE,
    aud: TOKEN_URL,
    iat: now,
    exp: now + 3600,
  };

  const unsigned = `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(claim))}`;
  const key = await importPrivateKey(env.SA_PRIVATE_KEY);
  const sigBuf = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    key,
    new TextEncoder().encode(unsigned),
  );
  const jwt = `${unsigned}.${b64urlBytes(new Uint8Array(sigBuf))}`;

  const resp = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: jwt,
    }),
  });
  if (!resp.ok) {
    throw new Error(`token ${resp.status}: ${await resp.text()}`);
  }
  return (await resp.json()).access_token;
}

async function importPrivateKey(pem) {
  const clean = pem
    .replace(/\\n/g, '\n')
    .replace('-----BEGIN PRIVATE KEY-----', '')
    .replace('-----END PRIVATE KEY-----', '')
    .replace(/\s/g, '');
  const der = Uint8Array.from(atob(clean), (c) => c.charCodeAt(0));
  return crypto.subtle.importKey(
    'pkcs8',
    der.buffer,
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['sign'],
  );
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

function b64url(str) {
  return b64urlBytes(new TextEncoder().encode(str));
}

function b64urlBytes(bytes) {
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
