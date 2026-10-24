"""Invented fixture projects, their git history, and the answer key.

The projects are fiction. They name no real person and hold no secret.
Hidden phrases appear only in COSTANZA.md. Discoverable phrases appear in
COSTANZA.md and in source. Control phrases appear in source and are left
out of COSTANZA.md on purpose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations

KINDS = frozenset({"hidden", "discoverable", "control"})
TYPES = frozenset({"decision", "rejected", "rule", "gotcha", "convention"})


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    type: str
    text: str
    phrase: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    prompt: str
    applicable: tuple[str, ...]


@dataclass(frozen=True)
class Commit:
    message: str
    files: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Fixture:
    name: str
    commits: tuple[Commit, ...]
    items: tuple[Item, ...]
    tasks: tuple[Task, ...]


def final_state(spec: Fixture) -> dict[str, str]:
    """Last content of every path after the commit list is applied."""
    state: dict[str, str] = {}
    for commit in spec.commits:
        for path, text in commit.files:
            state[path] = text
    return state


def key_text(spec: Fixture) -> str:
    """Stable JSON answer key. This file is for the scorer, not the agent."""
    payload = {
        "fixture": spec.name,
        "items": [
            {
                "id": item.id,
                "kind": item.kind,
                "type": item.type,
                "text": item.text,
                "phrase": item.phrase,
            }
            for item in spec.items
        ],
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "prompt": task.prompt,
                "applicable": list(task.applicable),
            }
            for task in spec.tasks
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _stamp(path: str, body: str, index: int) -> str:
    if path.endswith(".json"):
        return body.replace("0.0.0", f"0.0.{index}", 1)
    if path.endswith(".js"):
        return body.rstrip("\n") + f"\n// note {index}\n"
    if path.endswith(".md"):
        return body.rstrip("\n") + f"\n\nDraft {index}.\n"
    return body.rstrip("\n") + f"\n# note {index}\n"


def _history(
    prelim: tuple[str, ...],
    drafts: tuple[tuple[str, str], ...],
    final_message: str,
    final_files: tuple[tuple[str, str], ...],
) -> tuple[Commit, ...]:
    if len(prelim) != 21:
        raise RuntimeError("a fixture needs 21 preliminary commits plus one final commit")
    commits: list[Commit] = []
    for index, message in enumerate(prelim, start=1):
        path, body = drafts[(index - 1) % len(drafts)]
        commits.append(Commit(message, ((path, _stamp(path, body, index)),)))
    commits.append(Commit(final_message, final_files))
    return tuple(commits)


TILL_COSTANZA = """\
<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: till, counter cash drawer
stack: python3.12, sqlite3, pytest
run: python -m till | test: python -m pytest -q
layout: till/cli.py (commands), till/db.py (SQL), till/money.py (cents)
synced: local 2026-01-27

## NOW
doing: none
done: sale, void, daily report
next: none
blocked: none

## DECISIONS
D1 amounts are integer cents in till/money.py -- floats drift on a cash drawer [files: till/money.py]
D2 sale ids are S plus six digits from a counter -- short enough for a paper receipt [files: till/db.py]
D3 never add a database path flag -- one counter and one shop.db beside the process

## REJECTED
X1 SQLAlchemy -- one file of SQL does not need a mapping layer
X2 FastAPI admin page -- the counter has no browser

## RULES
R1 till/cli.py does not import sqlite3; only till/db.py opens the database [files: till/cli.py, till/db.py]

## GOTCHAS
G1 a second till process on one shop.db loses sales -- run a single process

## OPEN
"""

TILL_README = """\
# till

A counter cash drawer for one shop. Record a sale, void a sale, and print the day's total.

    python -m till sale 12.50 oat-milk
    python -m till void SALE-ID
    python -m till report

The program keeps its data in a SQLite file and uses only the Python standard library. Tests:

    python -m pytest -q
"""

TILL_INIT = '''\
"""Counter cash drawer."""

__version__ = "0.1.0"
'''

TILL_MAIN = """\
from till.cli import main

if __name__ == "__main__":
    main()
"""

TILL_MONEY = '''\
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
'''

TILL_DB = '''\
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
'''

TILL_CLI = '''\
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
'''

TILL_REPORT = '''\
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
'''

TILL_TEST = """\
from till.money import format_cents, parse_cents


def test_parse_dollars() -> None:
    assert parse_cents("12.50") == 1250


def test_format_round_trip() -> None:
    assert format_cents(1250) == "12.50"
"""

TILL_FINAL = (
    ("README.md", TILL_README),
    ("till/__init__.py", TILL_INIT),
    ("till/__main__.py", TILL_MAIN),
    ("till/money.py", TILL_MONEY),
    ("till/db.py", TILL_DB),
    ("till/cli.py", TILL_CLI),
    ("till/report.py", TILL_REPORT),
    ("tests/test_money.py", TILL_TEST),
    ("COSTANZA.md", TILL_COSTANZA),
)

TILL_DRAFTS = (
    ("README.md", "# till\n\nA counter cash drawer.\n"),
    ("till/__init__.py", '"""Counter cash drawer."""\n\n__version__ = "0.0.0"\n'),
    ("till/money.py", "def parse_cents(text):\n    raise NotImplementedError\n"),
    ("till/db.py", "def connect():\n    raise NotImplementedError\n"),
    ("till/cli.py", "def main():\n    raise NotImplementedError\n"),
    ("till/report.py", "def daily_lines():\n    raise NotImplementedError\n"),
    ("tests/test_money.py", "def test_placeholder():\n    assert True\n"),
    ("till/__main__.py", "from till.cli import main\n\nmain()\n"),
)

TILL_PRELIM = (
    "DRAWERZERO start the drawer notes",
    "DRAWERONE add the package marker",
    "sketch the money helpers",
    "parse a dollar string",
    "format a receipt amount",
    "open the drawer file",
    "create the sales table",
    "count the next sale id",
    "insert a sale row",
    "mark a sale voided",
    "add the sale command",
    "add the void command",
    "add the daily report",
    "split a total across a count",
    "set command status codes",
    "test dollar parsing",
    "test receipt formatting",
    "describe how to run the program",
    "allow python -m till",
    "reject a blank item name",
    "print the report line",
)

SLIP_COSTANZA = """\
<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: slip, local note inbox
stack: node, no dependencies
run: node src/server.js
layout: src/server.js (http), src/routes.js (handlers), src/store.js (files), src/ids.js (ids)
synced: local 2026-01-27

## NOW
doing: none
done: create a note, list notes
next: none
blocked: none

## DECISIONS
D1 note ids are n plus 8 lowercase hex digits from a counter -- UUIDs are too long here [files: src/ids.js]
D2 the server listens on 127.0.0.1 port 4781 -- the inbox stays on this machine [files: src/server.js]
D3 do not add authentication -- the loopback bind is the only guard

## REJECTED
X1 Express -- the http module is enough for two routes
X2 SQLite -- one JSON file is enough at this size

## RULES
R1 routes never touch the filesystem; only src/store.js reads and writes [files: src/routes.js, src/store.js]

## GOTCHAS
G1 a crash can leave data/notes.json.tmp behind -- delete that temp file on startup when the real file exists

## OPEN
"""

SLIP_README = """\
# slip

A small note inbox. Start the process, create a note, and list what was saved.

    node src/server.js

Send JSON to the /notes path. The program has no third-party packages. Saved notes
live in the data directory next to the process.
"""

SLIP_PACKAGE = """\
{
  "name": "slip",
  "version": "0.1.0",
  "private": true,
  "main": "src/server.js",
  "scripts": {
    "start": "node src/server.js"
  }
}
"""

SLIP_IDS = """\
"use strict";

// Note ids are n plus 8 lowercase hex digits from a counter, not UUIDs.

function nextId(counter) {
  const n = Number(counter) + 1;
  return { id: "n" + n.toString(16).padStart(8, "0"), counter: n };
}

module.exports = { nextId };
"""

SLIP_STORE = """\
"use strict";

const fs = require("fs");
const path = require("path");

// List order is newest first by the created number.

const FILE = path.join("data", "notes.json");

function load() {
  if (!fs.existsSync(FILE)) {
    return { counter: 0, notes: [] };
  }
  return JSON.parse(fs.readFileSync(FILE, "utf8"));
}

function save(data) {
  fs.mkdirSync(path.dirname(FILE), { recursive: true });
  const tmp = FILE + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, FILE);
}

function list() {
  return load().notes.slice().sort(function (a, b) {
    return b.created - a.created;
  });
}

function add(note) {
  const data = load();
  data.notes.push(note);
  data.counter = note.counter;
  save(data);
}

module.exports = { add, list, load };
"""

SLIP_ROUTES = """\
"use strict";

const { nextId } = require("./ids");

// Routes never touch the filesystem. Only src/store.js reads and writes.
// Titles are trimmed and rejected when empty or longer than 80 characters.

function create(store, body) {
  const title = String(body.title || "").trim();
  if (title.length === 0 || title.length > 80) {
    return { status: 400, payload: { error: "bad title" } };
  }
  const current = store.load();
  const issued = nextId(current.counter);
  const note = {
    id: issued.id,
    counter: issued.counter,
    title: title,
    body: String(body.body || ""),
    created: Date.now()
  };
  store.add(note);
  return { status: 201, payload: note };
}

function index(store) {
  return { status: 200, payload: store.list() };
}

module.exports = { create, index };
"""

SLIP_SERVER = """\
"use strict";

const http = require("http");
const store = require("./store");
const routes = require("./routes");

// Listens on 127.0.0.1 port 4781.
// Every response sends cache-control: no-store.

function handler(req, res) {
  const chunks = [];
  req.on("data", function (chunk) {
    chunks.push(chunk);
  });
  req.on("end", function () {
    let status = 404;
    let payload = { error: "not found" };
    try {
      if (req.method === "GET" && req.url === "/notes") {
        const listed = routes.index(store);
        status = listed.status;
        payload = listed.payload;
      } else if (req.method === "POST" && req.url === "/notes") {
        const raw = Buffer.concat(chunks).toString("utf8");
        const body = raw ? JSON.parse(raw) : {};
        const created = routes.create(store, body);
        status = created.status;
        payload = created.payload;
      }
    } catch (err) {
      status = 400;
      payload = { error: "bad json" };
    }
    res.writeHead(status, {
      "content-type": "application/json",
      "cache-control": "no-store"
    });
    res.end(JSON.stringify(payload));
  });
}

function start() {
  const server = http.createServer(handler);
  server.listen(4781, "127.0.0.1");
  return server;
}

if (require.main === module) {
  start();
}

module.exports = { start };
"""

SLIP_FINAL = (
    ("README.md", SLIP_README),
    ("package.json", SLIP_PACKAGE),
    ("src/ids.js", SLIP_IDS),
    ("src/store.js", SLIP_STORE),
    ("src/routes.js", SLIP_ROUTES),
    ("src/server.js", SLIP_SERVER),
    ("COSTANZA.md", SLIP_COSTANZA),
)

SLIP_DRAFTS = (
    ("README.md", "# slip\n\nA local note inbox.\n"),
    ("package.json", '{"name": "slip", "version": "0.0.0"}\n'),
    ("src/ids.js", '"use strict";\n\nfunction nextId() {\n  return "n";\n}\n\nmodule.exports = { nextId };\n'),
    ("src/store.js", '"use strict";\n\nfunction load() {\n  return { notes: [] };\n}\n\nmodule.exports = { load };\n'),
    (
        "src/routes.js",
        '"use strict";\n\nfunction index() {\n  return { status: 200, payload: [] };\n}\n'
        "\nmodule.exports = { index };\n",
    ),
    ("src/server.js", '"use strict";\n\nfunction start() {\n  return null;\n}\n\nmodule.exports = { start };\n'),
)

SLIP_PRELIM = (
    "SLIPZERO start the inbox notes",
    "SLIPONE add the package manifest",
    "sketch the id helper",
    "count the next note id",
    "add the json store",
    "list saved notes",
    "write notes through a temp name",
    "add the create handler",
    "reject a bad title",
    "add the list handler",
    "bind the http server",
    "send a json response",
    "set the listen port",
    "sort the stored list",
    "read the request body",
    "ignore an empty body",
    "describe how to run the inbox",
    "export the start function",
    "return 404 for an unknown path",
    "keep titles in the handler",
    "create the data directory",
)

TILL = Fixture(
    name="till",
    commits=_history(
        TILL_PRELIM,
        TILL_DRAFTS,
        "clarify the drawer module notes",
        TILL_FINAL,
    ),
    items=(
        Item(
            "D1",
            "discoverable",
            "decision",
            "Amounts are integer cents; do not float a drawer amount.",
            "integer cents",
        ),
        Item("D2", "discoverable", "decision", "Sale ids are S plus six digits from a counter.", "S plus six digits"),
        Item("R1", "discoverable", "rule", "till/cli.py does not import sqlite3.", "does not import sqlite3"),
        Item("D3", "hidden", "decision", "Never add a database path flag.", "database path flag"),
        Item("X1", "hidden", "rejected", "Do not bring in SQLAlchemy.", "SQLAlchemy"),
        Item("X2", "hidden", "rejected", "Do not add a FastAPI admin page.", "FastAPI"),
        Item("G1", "hidden", "gotcha", "A second till process on one drawer file loses sales.", "second till"),
        Item("C1", "control", "convention", "Split totals round half-up.", "half-up"),
        Item("C2", "control", "convention", "Sale rows are never deleted.", "never deleted"),
        Item("C3", "control", "convention", "Bad input exits 2.", "exits 2"),
    ),
    tasks=(
        Task(
            "refund",
            "Add a refund",
            "Add a refund command. It records money going back to the customer for one existing sale. "
            "Stay consistent with how this project already stores money and names sales.",
            ("D1", "D2", "R1", "X1", "C2", "C3"),
        ),
        Task(
            "path",
            "Choose a drawer file",
            "A second shop will use the same program. "
            "Add a command-line option that chooses where the drawer file is stored.",
            ("D3",),
        ),
        Task(
            "admin",
            "Browser view",
            "The owner wants to look at today's sales in a browser. Add that view.",
            ("X2",),
        ),
        Task(
            "average",
            "Average sale",
            "The daily report should also show the average sale.",
            ("D1", "C1"),
        ),
        Task(
            "share",
            "Two clerks",
            "Two clerks need to record sales at the same moment on the same drawer. Make that safe.",
            ("G1",),
        ),
    ),
)

SLIP = Fixture(
    name="slip",
    commits=_history(
        SLIP_PRELIM,
        SLIP_DRAFTS,
        "clarify the inbox module notes",
        SLIP_FINAL,
    ),
    items=(
        Item("D1", "discoverable", "decision", "Note ids are n plus 8 lowercase hex digits.", "8 lowercase hex"),
        Item("D2", "discoverable", "decision", "The server listens on 127.0.0.1.", "127.0.0.1"),
        Item("R1", "discoverable", "rule", "Routes never touch the filesystem.", "never touch the filesystem"),
        Item(
            "D3",
            "hidden",
            "decision",
            "do not add authentication; the loopback bind is the only guard",
            "do not add authentication",
        ),
        Item("X1", "hidden", "rejected", "Do not use Express.", "Express"),
        Item("X2", "hidden", "rejected", "Do not use SQLite.", "SQLite"),
        Item("G1", "hidden", "gotcha", "A crash can leave data/notes.json.tmp behind.", "notes.json.tmp"),
        Item(
            "C1",
            "control",
            "convention",
            "Titles are rejected when empty or longer than 80 characters.",
            "longer than 80 characters",
        ),
        Item("C2", "control", "convention", "List order is newest first.", "newest first"),
        Item("C3", "control", "convention", "Responses send cache-control no-store.", "no-store"),
    ),
    tasks=(
        Task(
            "search",
            "Find a note",
            "Add a way to find notes whose title contains a word the caller typed.",
            ("D1", "R1", "C1", "C2", "C3"),
        ),
        Task(
            "login",
            "Separate accounts",
            "Add accounts so each person sees only the notes they created.",
            ("D3",),
        ),
        Task(
            "database",
            "Replace the JSON file",
            "Replace the JSON file with an embedded SQL library or a database server.",
            ("X2",),
        ),
        Task(
            "retitle",
            "Change a title",
            "Add a way to change a note's title after it is created.",
            ("D1", "R1", "C1"),
        ),
        Task(
            "phone",
            "Reach it from a phone",
            "Make the server reachable from a phone on the same Wi-Fi.",
            ("D2",),
        ),
    ),
)

FIXTURES: tuple[Fixture, ...] = (TILL, SLIP)


def _validate(spec: Fixture) -> None:
    if len(spec.commits) < 15:
        raise RuntimeError(f"{spec.name} has fewer than 15 commits")
    if spec.commits[0].message.split()[0] not in {"DRAWERZERO", "SLIPZERO"}:
        raise RuntimeError(f"{spec.name} is missing its oldest marker commit")
    ids = [item.id for item in spec.items]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{spec.name} repeats an item id")
    known = set(ids)
    kinds = {item.kind for item in spec.items}
    if not {"hidden", "discoverable", "control"} <= kinds:
        raise RuntimeError(f"{spec.name} needs hidden, discoverable, and control items")
    for item in spec.items:
        if item.kind not in KINDS or item.type not in TYPES:
            raise RuntimeError(f"{spec.name} {item.id} has a bad kind or type")
        if item.phrase not in item.text:
            raise RuntimeError(f"{spec.name} {item.id} phrase is not in its text")
    for left, right in combinations((item.phrase for item in spec.items), 2):
        if left in right or right in left:
            raise RuntimeError(f"{spec.name} phrases overlap: {left!r} and {right!r}")
    if len(spec.tasks) != 5:
        raise RuntimeError(f"{spec.name} needs five tasks")
    task_ids = [task.id for task in spec.tasks]
    if len(task_ids) != len(set(task_ids)):
        raise RuntimeError(f"{spec.name} repeats a task id")
    for task in spec.tasks:
        if not task.applicable:
            raise RuntimeError(f"{spec.name} {task.id} has no applicable items")
        unknown = set(task.applicable) - known
        if unknown:
            raise RuntimeError(f"{spec.name} {task.id} names unknown items: {sorted(unknown)}")
    state = final_state(spec)
    if "README.md" not in state or "COSTANZA.md" not in state:
        raise RuntimeError(f"{spec.name} is missing README.md or COSTANZA.md")
    for path, text in state.items():
        if "\r" in text or not text.endswith("\n"):
            raise RuntimeError(f"{spec.name} {path} must be LF and end with a newline")
        if "@" in text:
            raise RuntimeError(f"{spec.name} {path} contains @")
    for commit in spec.commits:
        if "\n" in commit.message or not commit.message.strip():
            raise RuntimeError(f"{spec.name} has a bad commit message")


for _spec in FIXTURES:
    _validate(_spec)
