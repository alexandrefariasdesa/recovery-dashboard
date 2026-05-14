def normalize_phone(phone) -> str:
    s = str(phone or "").strip()
    if "." in s:
        s = s.split(".")[0]
    digits = "".join(c for c in s if c.isdigit())
    # Remove prefixo 55 do Brasil
    if len(digits) >= 12 and digits.startswith("55"):
        digits = digits[2:]
    return digits


def phone_variants(phone: str) -> set[str]:
    """
    Retorna todas as variantes do número para cobrir o formato com/sem o 9 do celular BR.
    Ex: '9294305962' (10d) e '92994305962' (11d) são o mesmo número.
    """
    p = normalize_phone(phone)
    variants = {p}
    if len(p) == 10:
        # Adiciona variante com 9 após o DDD (ex: 92|94305962 → 92|9|94305962)
        variants.add(p[:2] + "9" + p[2:])
    elif len(p) == 11 and p[2] == "9":
        # Adiciona variante sem o 9 (ex: 92|9|94305962 → 92|94305962)
        variants.add(p[:2] + p[3:])
    return variants
