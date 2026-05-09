def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 13 and digits.startswith("55"):
        digits = digits[2:]
    elif len(digits) == 12 and digits.startswith("55"):
        digits = digits[2:]
    return digits
