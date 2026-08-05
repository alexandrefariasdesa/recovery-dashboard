"""
Backfill do histórico das planilhas → Postgres (Fase 3 da migração).

Migra o "Papel A": recuperacoes → recovery_events, Leads/compras → compras.
NÃO toca nas planilhas nem no Make.

Uso:
  python db/backfill.py            # DRY-RUN: só conta e mostra período/tipos
  python db/backfill.py --apply    # grava (TRUNCATE + insere o histórico todo)

Idempotente no --apply: trunca as tabelas destino antes de inserir, então rodar
de novo não duplica. Os eventos que já chegaram pelo webhook são reinseridos a
partir da planilha (o Make gravou os mesmos lá), sem perda.
"""
import os
import re
import sys
import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP = ZoneInfo("America/Sao_Paulo")


def load_env(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.strip()] = v.strip()
    return d


ENV = {**load_env(os.path.join(ROOT, ".env")), **load_env(os.path.join(ROOT, ".env.supabase"))}
SB_URL = ENV["SB_URL"]
SB_KEY = ENV["SB_SERVICE_KEY"]
SA_FILE = os.path.join(ROOT, ENV.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

APPLY = "--apply" in sys.argv


def gclient():
    return gspread.authorize(Credentials.from_service_account_file(SA_FILE, scopes=SCOPES))


def read_tab(sid, tab):
    ws = gclient().open_by_key(sid).worksheet(tab)
    return ws.get_all_records()


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
    """Parseia a data da planilha (naïve, hora de São Paulo) → ISO UTC."""
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19], fmt)
            return dt.replace(tzinfo=SP).astimezone(ZoneInfo("UTC")).isoformat()
        except ValueError:
            continue
    # ISO com fuso já embutido
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ZoneInfo("UTC")).isoformat()
    except ValueError:
        return None


def to_valor(v, cents_detect):
    try:
        n = float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None
    if cents_detect and n >= 1000 and n % 1 == 0:
        n = n / 100
    return round(n, 2)


def sb_insert(table, rows, truncate=False):
    if truncate:
        # TRUNCATE via RPC não existe; usa DELETE ALL pelo PostgREST.
        req = urllib.request.Request(
            f"{SB_URL}/rest/v1/{table}?id=gte.0",
            method="DELETE",
            headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Prefer": "return=minimal"},
        )
        urllib.request.urlopen(req).read()
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        body = json.dumps(chunk).encode("utf-8")
        req = urllib.request.Request(
            f"{SB_URL}/rest/v1/{table}",
            data=body,
            method="POST",
            headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        urllib.request.urlopen(req).read()


def summarize(label, rows, date_key):
    dates = [r[date_key] for r in rows if r.get(date_key)]
    dmin = min(dates) if dates else "?"
    dmax = max(dates) if dates else "?"
    print(f"  {label}: {len(rows)} linhas | período {dmin[:10]} → {dmax[:10]}")


def main():
    print(f"=== BACKFILL {'(APLICANDO)' if APPLY else '(DRY-RUN — nada é gravado)'} ===\n")

    # ---- recuperacoes → recovery_events ----
    rec_raw = read_tab(ENV["SPREADSHEET_ID"], "recuperacoes")
    rec_rows = []
    for r in rec_raw:
        low = {str(k).strip().lower(): v for k, v in r.items()}
        # Mantém eventos SEM telefone: o dashboard conta eles no total (só não
        # convertem, por não ter como cruzar). Excluí-los distorcia total/receita.
        tel = norm_phone(low.get("telefone", ""))
        rec_rows.append({
            "evento_em": to_utc_iso(low.get("evento_em")) or None,
            "tipo": clean_tipo(low.get("tipo")),
            "nome": (low.get("nome") or None),
            "telefone": (tel or None),
            "valor": to_valor(low.get("valor"), cents_detect=False),  # recuperacoes já em reais
        })
    rec_rows = [r for r in rec_rows if r["evento_em"]]

    # ---- Leads/compras → compras ----
    comp_raw = read_tab(ENV["COMPRADORES_SPREADSHEET_ID"], ENV.get("COMPRADORES_TAB", "Leads"))
    comp_rows = []
    for r in comp_raw:
        low = {str(k).strip().lower(): v for k, v in r.items()}
        tel = norm_phone(low.get("telefone") or low.get("phone") or low.get("celular", ""))
        if not tel:
            continue
        # Data da compra: a coluna real é "data de criação". Casa por "cria" no
        # nome (mesma heurística do dashboard) + nomes exatos.
        compra_em = None
        for k, v in low.items():
            kn = str(k).strip().lower()
            if v and ("cria" in kn or kn in ("created_at", "data", "compra_em")):
                compra_em = to_utc_iso(v); break
        valor = None
        for k in ("valor", "preço", "preco", "price"):
            if low.get(k) not in (None, ""):
                valor = to_valor(low[k], cents_detect=True); break
        comp_rows.append({
            "compra_em": compra_em,
            "nome": (low.get("nome") or None),
            "telefone": tel,
            "valor": valor,
            "produto": (low.get("produto") or low.get("product") or None),
            "transaction_id": None,
        })
    comp_rows = [r for r in comp_rows if r["compra_em"]]

    # ---- eventos_manychat → manychat_eventos ----
    ev_raw = read_tab(ENV["SPREADSHEET_ID"], "eventos_manychat")
    ev_rows = []
    for r in ev_raw:
        low = {str(k).strip().lower(): v for k, v in r.items()}
        em = to_utc_iso(low.get("ts") or low.get("evento_em"))
        if not em:
            continue
        ev_rows.append({
            "evento_em": em,
            "telefone": (norm_phone(low.get("telefone", "")) or None),
            "subscriber_id": (str(low.get("subscriber_id") or "") or None),
            "fluxo": clean_tipo(low.get("fluxo")),
            "etapa": clean_tipo(low.get("etapa")),
        })

    # ---- cliques_manychat → manychat_cliques ----
    cl_raw = read_tab(ENV["SPREADSHEET_ID"], "cliques_manychat")
    cl_rows = []
    for r in cl_raw:
        low = {str(k).strip().lower(): v for k, v in r.items()}
        cem = to_utc_iso(low.get("clicado_em"))
        if not cem:
            continue
        cl_rows.append({
            "clicado_em": cem,
            "telefone": (norm_phone(low.get("telefone", "")) or None),
            "subscriber_id": (str(low.get("subscriber_id") or "") or None),
            "tipo": clean_tipo(low.get("tipo")),
            "url": (low.get("url") or None),
        })

    print("O que será importado:")
    summarize("recovery_events (de recuperacoes)", rec_rows, "evento_em")
    from collections import Counter
    tc = Counter(r["tipo"] for r in rec_rows)
    print("    tipos:", dict(tc))
    summarize("compras (de Leads)", comp_rows, "compra_em")
    summarize("manychat_eventos (de eventos_manychat)", ev_rows, "evento_em")
    summarize("manychat_cliques (de cliques_manychat)", cl_rows, "clicado_em")

    if not APPLY:
        print("\nDRY-RUN. Rode com --apply para gravar.")
        return

    print("\nGravando (TRUNCATE + insert)...")
    sb_insert("recovery_events", rec_rows, truncate=True)
    sb_insert("compras", comp_rows, truncate=True)
    sb_insert("manychat_eventos", ev_rows, truncate=True)
    sb_insert("manychat_cliques", cl_rows, truncate=True)
    print(f"OK: {len(rec_rows)} recovery_events, {len(comp_rows)} compras, "
          f"{len(ev_rows)} manychat_eventos, {len(cl_rows)} manychat_cliques.")


if __name__ == "__main__":
    main()
