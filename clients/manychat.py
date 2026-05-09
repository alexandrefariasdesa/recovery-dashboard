import requests
from functools import lru_cache
import config
from clients.payt import normalize_phone

_BASE = "https://api.manychat.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.MANYCHAT_TOKEN}",
        "Content-Type": "application/json",
    }


@lru_cache(maxsize=1)
def _custom_field_map() -> dict:
    """Returns {field_name: field_id} mapping from ManyChat account."""
    resp = requests.get(f"{_BASE}/fb/custom_fields", headers=_headers(), timeout=30)
    resp.raise_for_status()
    return {f["name"]: str(f["id"]) for f in resp.json().get("data", [])}


def _resolve_field_id(name_or_id: str) -> str:
    """Return the numeric field ID for a given field name or passthrough if already an ID."""
    if name_or_id.isdigit():
        return name_or_id
    mapping = _custom_field_map()
    resolved = mapping.get(name_or_id)
    if not resolved:
        raise ValueError(
            f"Custom field '{name_or_id}' não encontrado no ManyChat. "
            f"Campos disponíveis: {list(mapping.keys())}"
        )
    return resolved


def _extract_phone(sub: dict) -> str:
    """Try multiple paths to find phone number in a subscriber object."""
    for key in ("phone", "phone_number", "wa_id", "whatsapp_phone"):
        val = sub.get(key, "")
        if val:
            return normalize_phone(str(val))
    for cf in sub.get("custom_fields", []):
        if cf.get("name", "").lower() in ("telefone", "phone", "celular", "whatsapp"):
            return normalize_phone(str(cf.get("value", "")))
    return ""


def get_subscribers_by_field(field_name_or_id: str, field_value: str = "true") -> list[dict]:
    """Return all subscribers where a custom field equals field_value."""
    if not field_name_or_id:
        return []

    field_id = _resolve_field_id(field_name_or_id)

    resp = requests.post(
        f"{_BASE}/fb/subscriber/findByCustomField",
        headers=_headers(),
        json={"field_id": field_id, "field_value": field_value},
        timeout=30,
    )
    resp.raise_for_status()

    subscribers = resp.json().get("data", [])
    for sub in subscribers:
        sub["phone_normalized"] = _extract_phone(sub)

    return subscribers


def get_all_recovery_subscribers() -> list[dict]:
    """
    Union of all subscribers who received any recovery sequence.
    A subscriber can appear once per recovery type if they received multiple.
    """
    recovery_types = [
        ("boleto", config.MC_FIELD_BOLETO_SENT),
        ("pix", config.MC_FIELD_PIX_SENT),
        ("cart", config.MC_FIELD_CART_SENT),
    ]

    # subscriber_id -> {sub_data, recovery_types: []}
    seen: dict[str, dict] = {}

    for recovery_type, field in recovery_types:
        if not field:
            continue
        try:
            subscribers = get_subscribers_by_field(field, "true")
        except Exception as exc:
            raise RuntimeError(f"Erro ao buscar recovery '{recovery_type}': {exc}") from exc

        for sub in subscribers:
            sid = sub["id"]
            if sid not in seen:
                seen[sid] = {**sub, "recovery_types": []}
            seen[sid]["recovery_types"].append(recovery_type)

    # Flatten: one entry per (subscriber, recovery_type)
    rows = []
    for sub_data in seen.values():
        for rt in sub_data["recovery_types"]:
            rows.append({**sub_data, "recovery_type": rt})

    return rows
