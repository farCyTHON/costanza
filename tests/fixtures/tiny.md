<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: shopbot, Telegram order bot
stack: python3.12, FastAPI, SQLite, pytest
run: uvicorn app.main:app | test: pytest -q
layout: app/routes (HTTP), app/services (logic), app/db (queries)
synced: a1b2c3d 2026-10-12

## NOW
doing: payment webhook retries (app/services/pay.py)
done: auth, cart, order model
next: backoff, admin export
blocked: none

## DECISIONS
D1 SQLite, not Postgres -- single node, zero ops
D2 services never import routes; all DB access goes through app/db

## REJECTED
X1 SQLAlchemy -- too heavy here; raw SQL in app/db

## RULES
R1 type hints required; use the logger, never print

## GOTCHAS
G1 webhook sends duplicate events -- dedupe on event_id

## OPEN
Q1 rate limit per user or per IP -- not decided
