import requests
from datetime import date
from typing import Optional
import config


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.PAYT_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 13 and digits.startswith("55"):
        digits = digits[2:]
    elif len(digits) == 12 and digits.startswith("55"):
        digits = digits[2:]
    return digits


def _enrich(transactions: list[dict]) -> list[dict]:
    for t in transactions:
        customer = t.get("customer", {})
        customer["phone_normalized"] = normalize_phone(customer.get("phone", ""))
    return transactions


def _fetch_paginated(endpoint: str, params: dict) -> list[dict]:
    all_items = []
    page = 1

    while True:
        resp = requests.get(
            f"{config.PAYT_BASE_URL}{endpoint}",
            headers=_headers(),
            params={**params, "page": page, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("data", [])
        all_items.extend(items)

        meta = data.get("meta", {})
        if page >= meta.get("total_pages", 1) or not items:
            break
        page += 1

    return all_items


def get_transactions(
    start_date: date,
    end_date: date,
    status: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> list[dict]:
    params: dict = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    if status:
        params["status"] = status
    if payment_method:
        params["payment_method"] = payment_method

    return _enrich(_fetch_paginated("/transactions", params))


def get_paid_transactions(start_date: date, end_date: date) -> list[dict]:
    return get_transactions(start_date, end_date, status="paid")


def get_recovery_candidates(start_date: date, end_date: date) -> dict[str, list[dict]]:
    """
    Returns unpaid transactions grouped by recovery type.
    Boleto: expired/overdue boletos that were never paid.
    PIX: expired PIX transactions.
    Cart: abandoned checkouts.
    """
    boleto = []
    for status in config.PAYT_BOLETO_RECOVERY_STATUSES:
        boleto.extend(get_transactions(start_date, end_date, status=status, payment_method="boleto"))

    pix = []
    for status in config.PAYT_PIX_RECOVERY_STATUSES:
        pix.extend(get_transactions(start_date, end_date, status=status, payment_method="pix"))

    # Cart abandonment — endpoint may differ; handled gracefully if not available
    cart = _get_abandoned_checkouts(start_date, end_date)

    return {"boleto": boleto, "pix": pix, "cart": cart}


def _get_abandoned_checkouts(start_date: date, end_date: date) -> list[dict]:
    params = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "abandoned",
    }
    try:
        items = _fetch_paginated("/checkouts", params)
        return _enrich(items)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return []  # endpoint não disponível nessa conta Payt
        raise


def get_buyers_by_product(product_name: str, start_date: date, end_date: date) -> list[dict]:
    paid = get_paid_transactions(start_date, end_date)
    lower = product_name.lower()

    def _matches(t: dict) -> bool:
        if lower in t.get("product", {}).get("name", "").lower():
            return True
        return any(lower in item.get("name", "").lower() for item in t.get("items", []))

    return [t for t in paid if _matches(t)]
