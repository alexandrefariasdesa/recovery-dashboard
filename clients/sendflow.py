import requests
import config
from utils import normalize_phone


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.SENDFLOW_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_group_members(group_id: str = "") -> list[dict]:
    gid = group_id or config.SENDFLOW_GROUP_ID
    if not gid:
        raise ValueError("SENDFLOW_GROUP_ID não configurado no .env")

    all_members = []
    page = 1

    while True:
        resp = requests.get(
            f"{config.SENDFLOW_BASE_URL}/groups/{gid}/members",
            headers=_headers(),
            params={"page": page, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        members = data.get("data", [])
        for m in members:
            m["phone_normalized"] = normalize_phone(m.get("phone", ""))
        all_members.extend(members)

        meta = data.get("meta", {})
        if page >= meta.get("total_pages", 1) or not members:
            break
        page += 1

    return all_members
