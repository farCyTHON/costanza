"""Daily totals."""

from __future__ import annotations

from till.db import connect
from till.money import format_cents


def quantize_half_up(cents: int, parts: int) -> int:
    """Round a split total half-up, away from zero on a tie."""
    if parts <= 0:
        raise ValueError("parts")
    sign = -1 if cents < 0 else 1
    value = abs(cents)
    quotient, remainder = divmod(value, parts)
    if remainder * 2 >= parts:
        quotient += 1
    return sign * quotient


def average_cents(total: int, count: int) -> int:
    """Helper for a future average line. The report does not call this yet."""
    return quantize_half_up(total, count)


def daily_lines() -> list[str]:
    conn = connect()
    try:
        row = conn.execute(
            "select coalesce(sum(cents), 0) as total, count(*) as n "
            "from sales where voided = 0"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return ["sales 0", "total 0.00"]
    total = int(row["total"])
    count = int(row["n"])
    return [f"sales {count}", f"total {format_cents(total)}"]
