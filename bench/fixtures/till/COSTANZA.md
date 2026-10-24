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
