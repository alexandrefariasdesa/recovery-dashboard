import time
import requests
import config
from utils import normalize_phone


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.SENDFLOW_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def check_participant(phone_number: str) -> dict:
    """
    Verifica se um número está em algum grupo das campanhas da conta.
    Retorna o dict completo da API: {phoneNumber, found, releases, error}
    Rate limit: 1s entre chamadas (respeitado pelo chamador).
    """
    digits = normalize_phone(phone_number)
    # Garante formato 55 + DDD + número
    if len(digits) == 11:
        digits = "55" + digits
    elif len(digits) == 10:
        digits = "55" + digits

    payload = {
        "accountId": config.SENDFLOW_ACCOUNT_ID,
        "phoneNumber": digits,
        "timeout": 30000,
    }
    resp = requests.post(
        f"{config.SENDFLOW_BASE_URL}/actions/find-participant",
        headers=_headers(),
        json=payload,
        timeout=40,
    )
    if resp.status_code == 200:
        return resp.json()
    return {"phoneNumber": digits, "found": False, "releases": [], "error": str(resp.status_code)}


def is_in_target_group(result: dict) -> bool:
    """Retorna True se o número foi encontrado no grupo alvo configurado."""
    if not result.get("found"):
        return False
    target = config.SENDFLOW_GROUP_ID
    if not target:
        return result["found"]
    for release in result.get("releases", []):
        if target in release.get("groupIds", []):
            return True
    return False
