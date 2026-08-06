"""
Sync incremental Sheets → Postgres das abas de ManyChat (eventos + cliques).

Fecha o "live-gap": os Cloudflare Workers escrevem esses eventos SÓ no Sheets, e
o dashboard (com USE_POSTGRES) lê do banco. Este sync roda agendado (GitHub
Action) e traz pro Postgres as linhas novas que apareceram na planilha.

Cursor por ÍNDICE DE LINHA (tabela sync_state): a planilha é append-only, então
inserir `records[last_row:]` e avançar o cursor é à prova de duplicata.

Modos:
  python db/sync_manychat.py           # incremental (o normal, pro cron)
  python db/sync_manychat.py --init    # zera: TRUNCATE + re-sync total + cursor
                                        # (unifica backfill + cursor num read só)

Config (env ou .env/.env.supabase; no GitHub Action vem dos secrets):
  SB_URL, SB_SERVICE_KEY   — projeto Supabase do recovery
  SPREADSHEET_ID           — planilha com as abas eventos/cliques_manychat
  GCP_SA_JSON (env) OU service_account.json (arquivo) — leitura do Sheets
"""
import os
import re
import sys
import json
import urllib.request

import gspread
from google.oauth2.service_account import Credentials

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = "--init" in sys.argv


def load_env(path):
    if not os.path.exists(path):
        return {}
    d = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


ENV = {**load_env(os.path.join(ROOT, ".env")), **load_env(os.path.join(ROOT, ".env.supabase")), **os.environ}


def clean(v):
    # Tira BOM/aspas/espaços — secrets colados às vezes vêm com ﻿, e header
    # HTTP com BOM estoura UnicodeEncodeError latin-1.
    return str(v).strip().strip('"').strip("'").lstrip("﻿").strip()


SB_URL = clean(ENV["SB_URL"]).rstrip("/")
SB_KEY = clean(ENV["SB_SERVICE_KEY"])
SPREADSHEET_ID = clean(ENV["SPREADSHEET_ID"])
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def gclient():
    raw = os.environ.get("GCP_SA_JSON")
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            os.path.join(ROOT, ENV.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")), scopes=SCOPES)
    return gspread.authorize(creds)


# ── PostgREST helpers ────────────────────────────────────────────────────────
def sb(method, path, body=None, prefer=None):
    headers = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{SB_URL}/rest/v1/{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req) as r:
        txt = r.read().decode("utf-8")
        return json.loads(txt) if txt.strip() else None


def get_cursor(source):
    rows = sb("GET", f"sync_state?source=eq.{source}&select=last_row")
    return rows[0]["last_row"] if rows else 0


def set_cursor(source, n):
    from datetime import datetime, timezone
    sb("POST", "sync_state",
       [{"source": source, "last_row": n, "updated_at": datetime.now(timezone.utc).isoformat()}],
       prefer="resolution=merge-duplicates,return=minimal")


def insert_rows(table, rows):
    for i in range(0, len(rows), 500):
        sb("POST", table, rows[i:i + 500], prefer="return=minimal")


def truncate(table):
    sb("DELETE", f"{table}?id=gte.0", prefer="return=minimal")


# ── Mapeamento (mesmo do backfill) ───────────────────────────────────────────
def only_digits(s):
    return re.sub(r"\D", "", str(s or ""))


def norm_phone(s):
    d = only_digits(s)
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    return d


def clean_tipo(v):
    s = str(v or "").strip()
    if s.startswith("{{") and s.endswith("}}"):
        s = s.strip("{}").strip().strip('"').strip("'").strip()
    return s.lower()


def to_utc_iso(raw):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=ZoneInfo("America/Sao_Paulo")).astimezone(ZoneInfo("UTC")).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ZoneInfo("UTC")).isoformat()
    except ValueError:
        return None


def map_eventos(low):
    em = to_utc_iso(low.get("ts") or low.get("evento_em"))
    if not em:
        return None
    return {"evento_em": em, "telefone": (norm_phone(low.get("telefone", "")) or None),
            "subscriber_id": (str(low.get("subscriber_id") or "") or None),
            "fluxo": clean_tipo(low.get("fluxo")), "etapa": clean_tipo(low.get("etapa"))}


def map_cliques(low):
    cem = to_utc_iso(low.get("clicado_em"))
    if not cem:
        return None
    return {"clicado_em": cem, "telefone": (norm_phone(low.get("telefone", "")) or None),
            "subscriber_id": (str(low.get("subscriber_id") or "") or None),
            "tipo": clean_tipo(low.get("tipo")), "url": (low.get("url") or None)}


SOURCES = [
    ("eventos_manychat", "manychat_eventos", map_eventos),
    ("cliques_manychat", "manychat_cliques", map_cliques),
]


def main():
    gc = gclient()
    print(f"=== SYNC ManyChat {'(--init: reset total)' if INIT else '(incremental)'} ===")
    for tab, table, mapper in SOURCES:
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet(tab)
        records = ws.get_all_records()
        total = len(records)

        if INIT:
            truncate(table)
            cursor = 0
        else:
            cursor = get_cursor(tab)
            if cursor > total:
                # planilha encolheu (não deveria) — ressincroniza do zero.
                print(f"  {tab}: cursor {cursor} > planilha {total}; ressincronizando.")
                truncate(table)
                cursor = 0

        novos = [m for m in (mapper({str(k).strip().lower(): v for k, v in r.items()})
                             for r in records[cursor:]) if m]
        if novos:
            insert_rows(table, novos)
        set_cursor(tab, total)
        print(f"  {tab}: +{len(novos)} novas (planilha {total}, cursor {cursor}→{total})")


if __name__ == "__main__":
    main()
