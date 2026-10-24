"""Money as integer cents. Never float a drawer amount."""


def parse_cents(text: str) -> int:
    """Accept a dollar string and return cents."""
    cleaned = text.strip()
    negative = cleaned.startswith("-")
    if negative:
        cleaned = cleaned[1:]
    if "." in cleaned:
        whole, frac = cleaned.split(".", 1)
        if not whole.isdigit() or not frac.isdigit() or len(frac) > 2:
            raise ValueError("bad amount")
        frac = frac.ljust(2, "0")
        cents = int(whole) * 100 + int(frac)
    else:
        if not cleaned.isdigit():
            raise ValueError("bad amount")
        cents = int(cleaned) * 100
    return -cents if negative else cents


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{value // 100}.{value % 100:02d}"
