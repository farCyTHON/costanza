"""Commands. This module does not import sqlite3."""

from __future__ import annotations

import sys

from till.db import DrawerError, connect, insert_sale, next_sale_id, void_sale
from till.money import parse_cents
from till.report import daily_lines

# Bad input exits 2. A database error exits 1.


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args or args[0] in {"-h", "--help"}:
            print("usage: python -m till sale AMOUNT ITEM | void ID | report")
            return
        command, rest = args[0], args[1:]
        if command == "sale":
            _sale(rest)
        elif command == "void":
            _void(rest)
        elif command == "report":
            for line in daily_lines():
                print(line)
        else:
            raise ValueError("unknown command")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
    except DrawerError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


def _sale(rest: list[str]) -> None:
    if len(rest) != 2 or not rest[1].strip():
        raise ValueError("usage: sale AMOUNT ITEM")
    cents = parse_cents(rest[0])
    conn = connect()
    try:
        insert_sale(conn, next_sale_id(conn), cents, rest[1].strip())
    finally:
        conn.close()


def _void(rest: list[str]) -> None:
    if len(rest) != 1:
        raise ValueError("usage: void ID")
    conn = connect()
    try:
        void_sale(conn, rest[0])
    finally:
        conn.close()
