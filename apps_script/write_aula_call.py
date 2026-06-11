"""
Chamada para a AULA — gera a lista de disparo direto na planilha de COMPRAS,
usando o service account que o dashboard ja usa (sem popup/OAuth).

Publico: TODOS os compradores desde AULA_CUTOFF (sem filtro de grupo).
Controle SEPARADO da 2a chamada do grupo: usa a coluna `aula_chamada_em`
(NAO reusa `segunda_chamada_em`) — por isso a mesma pessoa pode estar nas
duas listas sem "casar".

Cadencia (roda de hora em hora):
  - hora < 18h  -> convida para a aula de HOJE   (convite_para="hoje",   aula_data=hoje)
  - hora >= 18h -> convida para a aula de AMANHA (convite_para="amanha", aula_data=amanha)

Fluxo:
  1. Garante a coluna `aula_chamada_em` na aba Leads (NAO sobrescreve valores).
  2. Monta a aba `Disparo Aula` com os elegiveis prontos (1 por telefone).
  3. Quem ja tem `aula_chamada_em` preenchido (Make marcou) sai da lista.

Make fecha o loop: ao disparar, grava `now` em `aula_chamada_em` (Update Row na
linha `leads_row`). A run da hora seguinte ve a coluna preenchida e nao reenvia.

PRE-REQUISITO: o service account precisa de acesso de EDITOR na planilha de compras
  recovery-dashboard@atomic-quasar-379600.iam.gserviceaccount.com

Uso:  python apps_script/write_aula_call.py
"""
import json
import os
import re
import sys
import tomllib
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

# Fuso do negocio (Manaus, UTC-4, sem horario de verao). Garante que a regra
# das 18h vale no horario LOCAL mesmo quando o runner roda em UTC (GitHub Actions).
TZ = ZoneInfo("America/Manaus")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import phone_variants, normalize_phone

# ── CONFIG ────────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_PATH = os.path.join(_ROOT, ".streamlit", "secrets.toml")
COMPRAS_TAB = "Leads"

# So convida quem comprou em/depois desta data. AJUSTE para o inicio da campanha
# da aula — um cutoff antigo joga MUITOS compradores na primeira leva.
AULA_CUTOFF = date(2026, 5, 10)

# Hora de corte: ate este horario convida pra HOJE; depois, pra AMANHA.
CUTOFF_HOUR = 18

# Coluna de controle PROPRIA da aula (independente da 2a chamada do grupo).
COL_CONTROLE = "aula_chamada_em"

# Aba de saida com os leads prontos pro disparo (o Make le esta aba).
DISPATCH_TAB = "Disparo Aula"

# Dados da aula que vao no template (preencha; viram colunas do disparo).
AULA_LINK = ""        # link da aula (zoom/youtube/etc)
AULA_HORARIO = ""     # ex: "20h"

DISPATCH_HEADER = [
    "telefone_e164", "primeiro_nome", "nome", "email", "produto",
    "convite_para", "aula_data", "aula_horario", "aula_link",
    "compra_em", "leads_row",
]

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]  # leitura + escrita
_PHONE_RE = re.compile(r"^55\d{10,11}$|^\d{10,11}$")


def _col_letter(idx_zero_based: int) -> str:
    n = idx_zero_based + 1
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _to_whatsapp(phone: str) -> str:
    """Formato WhatsApp E.164 BR: 55 + DDD + 9 digitos (adiciona o 9 se faltar)."""
    d = normalize_phone(phone)  # tira 55, deixa 10 ou 11 digitos
    if len(d) == 10:
        d = d[:2] + "9" + d[2:]
    return "55" + d if len(d) == 11 else ""


def _get_or_create(sh, title: str, cols: int):
    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=1000, cols=cols)


def _load_config() -> tuple[dict, str]:
    """Credenciais + ID da planilha. Nuvem usa env vars; local cai pro secrets.toml.

    Env (GitHub Actions):
      GCP_SA_JSON                 -> JSON do service account (string)
      COMPRADORES_SPREADSHEET_ID  -> id da planilha de compras
    """
    sa_env = os.environ.get("GCP_SA_JSON")
    if sa_env:
        sa_info = json.loads(sa_env)
        comprador_id = os.environ["COMPRADORES_SPREADSHEET_ID"]
        return sa_info, comprador_id
    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)
    return secrets["gcp_service_account"], secrets["COMPRADORES_SPREADSHEET_ID"]


def main() -> None:
    sa_info, comprador_id = _load_config()
    creds = Credentials.from_service_account_info(sa_info, scopes=_SCOPES)
    gc = gspread.authorize(creds)

    # ── Janela de convite (hoje vs amanha) pelo horario LOCAL (Manaus) ────────
    agora = datetime.now(TZ)
    if agora.hour < CUTOFF_HOUR:
        convite_para, aula_data = "hoje", agora.date()
    else:
        convite_para, aula_data = "amanha", agora.date() + timedelta(days=1)
    aula_data_str = aula_data.strftime("%d/%m/%Y")

    # ── Compras (Leads) ───────────────────────────────────────────────────────
    ws = gc.open_by_key(comprador_id).worksheet(COMPRAS_TAB)
    rows = ws.get_all_values()
    if len(rows) < 2:
        print("Aba de compras vazia.")
        return

    headers = [h.strip() for h in rows[0]]
    low = [h.lower() for h in headers]

    def _find(pred) -> int:
        for i, h in enumerate(low):
            if pred(h):
                return i
        return -1

    phone_idx = _find(lambda h: h in ("telefone", "phone", "whatsapp", "celular"))
    date_idx = _find(lambda h: "cria" in h or h in ("created_at", "data", "compra_em"))
    if phone_idx == -1 or date_idx == -1:
        raise SystemExit(f"Nao achei telefone({phone_idx})/data({date_idx}). Headers: {headers}")
    nome_idx = _find(lambda h: h in ("nome", "name"))
    email_idx = _find(lambda h: h in ("email", "e-mail"))
    produto_idx = _find(lambda h: h in ("produto", "product"))

    def _ensure(name: str) -> int:
        if name.lower() in low:
            return low.index(name.lower())
        headers.append(name)
        low.append(name.lower())
        return len(headers) - 1

    controle_idx = _ensure(COL_CONTROLE)

    eligible_by_phone: dict[str, list[str]] = {}  # dedup por telefone (1 disparo por pessoa)
    sent_phones: set[str] = set()                  # telefones com aula_chamada_em ja preenchido
    n_eleg = 0
    for sheet_row, r in enumerate(rows[1:], start=2):
        def cell(i):
            return r[i] if i >= 0 and i < len(r) else ""

        phone_key = normalize_phone(cell(phone_idx))

        compra_em = None
        raw = str(cell(date_idx)).strip()
        if raw:
            try:
                compra_em = datetime.fromisoformat(raw)
            except ValueError:
                compra_em = None
        data_ok = bool(compra_em and compra_em.date() >= AULA_CUTOFF)

        ja_chamado = str(cell(controle_idx)).strip() != ""
        if ja_chamado and phone_key:
            sent_phones.add(phone_key)  # qualquer linha marcada => pessoa ja recebeu

        elegivel = data_ok and (not ja_chamado)
        if elegivel:
            n_eleg += 1
            wa = _to_whatsapp(cell(phone_idx))
            if wa and phone_key not in eligible_by_phone:
                nome = str(cell(nome_idx)).strip()
                eligible_by_phone[phone_key] = [
                    wa,
                    nome.split()[0] if nome else "",
                    nome,
                    str(cell(email_idx)).strip(),
                    str(cell(produto_idx)).strip(),
                    convite_para,
                    aula_data_str,
                    AULA_HORARIO,
                    AULA_LINK,
                    raw,
                    str(sheet_row),  # leads_row: linha exata na Leads pro Make marcar
                ]

    # Exclui do disparo qualquer telefone com QUALQUER linha ja marcada na Leads
    for k in sent_phones:
        eligible_by_phone.pop(k, None)

    # ── Garante a coluna de controle na Leads (sem sobrescrever valores) ──────
    ws.update(
        [[COL_CONTROLE]],
        f"{_col_letter(controle_idx)}1:{_col_letter(controle_idx)}1",
        value_input_option="RAW",
    )

    # ── Aba de disparo: elegiveis prontos ─────────────────────────────────────
    sh = ws.spreadsheet
    dispatch_rows = list(eligible_by_phone.values())

    dispatch_ws = _get_or_create(sh, DISPATCH_TAB, cols=len(DISPATCH_HEADER))
    dispatch_ws.clear()
    values = [DISPATCH_HEADER] + dispatch_rows
    last_col = _col_letter(len(DISPATCH_HEADER) - 1)
    dispatch_ws.update(values, f"A1:{last_col}{len(values)}", value_input_option="RAW")

    print(f"Janela: convida para a aula de '{convite_para}' ({aula_data_str}) "
          f"[hora={agora.hour}h, corte={CUTOFF_HOUR}h]")
    print(f"Coluna de controle garantida: {COL_CONTROLE} ({_col_letter(controle_idx)})")
    print(
        f"Aba '{DISPATCH_TAB}': {len(dispatch_rows)} leads prontos pro disparo "
        f"({len(sent_phones)} ja marcados e excluidos)."
    )


if __name__ == "__main__":
    main()
