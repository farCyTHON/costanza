from till.money import format_cents, parse_cents


def test_parse_dollars() -> None:
    assert parse_cents("12.50") == 1250


def test_format_round_trip() -> None:
    assert format_cents(1250) == "12.50"
