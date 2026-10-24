"""SQLite access. Sale ids are S plus six digits."""

from __future__ import annotations

import sqlite3


class DrawerError(Exception):
    """A database failure the command layer can report."""


# Voided sales stay in the table. Rows are never deleted.


def connect() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect("shop.db")
    except sqlite3.Error as exc:
        raise DrawerError(str(exc)) from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            create table if not exists sales (
                id text primary key,
                cents integer not null,
                item text not null,
                voided integer not null default 0
            )
            """
        )
        conn.execute(
            """
            create table if not exists seq (
                name text primary key,
                n integer not null
            )
            """
        )
    except sqlite3.Error as exc:
        raise DrawerError(str(exc)) from exc
    return conn


def next_sale_id(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("select n from seq where name = 'sale'").fetchone()
        current = 0 if row is None else int(row["n"])
        nxt = current + 1
        conn.execute(
            "insert into seq (name, n) values ('sale', ?) "
            "on conflict(name) do update set n = excluded.n",
            (nxt,),
        )
    except sqlite3.Error as exc:
        raise DrawerError(str(exc)) from exc
    return f"S{nxt:06d}"


def insert_sale(conn: sqlite3.Connection, sale_id: str, cents: int, item: str) -> None:
    try:
        conn.execute(
            "insert into sales (id, cents, item, voided) values (?, ?, ?, 0)",
            (sale_id, cents, item),
        )
        conn.commit()
    except sqlite3.Error as exc:
        raise DrawerError(str(exc)) from exc


def void_sale(conn: sqlite3.Connection, sale_id: str) -> None:
    try:
        conn.execute("update sales set voided = 1 where id = ?", (sale_id,))
        conn.commit()
    except sqlite3.Error as exc:
        raise DrawerError(str(exc)) from exc
