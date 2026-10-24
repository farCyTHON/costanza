<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: shopbot, Telegram order bot for a three-shop bakery chain
stack: python3.12, FastAPI, SQLite, aiogram 3, httpx, pytest
run: uvicorn app.main:app --reload | test: pytest -q
layout: app/routes (HTTP), app/bot (Telegram handlers), app/services (logic), app/db (queries), app/jobs (scheduled), tests/
synced: 9f8e7d6 2026-10-12

## NOW
doing: payment webhook retries with backoff (app/services/pay.py, app/jobs/retry.py)
done: auth, cart, order model, shop hours, admin login, CSV menu import, refund flow, Sentry-free error log
next: admin export to CSV, per-shop stock limits, Ukrainian translations, load test before launch
blocked: Stripe test account needs business verification; waiting on owner (ETA Friday)

## DECISIONS
D1 SQLite, not Postgres -- single node, three shops, zero ops; WAL mode on @a1b2c3d [files: app/db/conn.py]
D2 services never import routes; all DB access goes through app/db
D3 money is integer cents everywhere, never float -- rounding bugs in refunds during the pilot @b2c3d4e
D4 one Telegram bot for all shops; shop chosen per chat and stored in chats.shop_id [files: app/bot/start.py]
D5 webhook mode in prod, long polling only in dev -- hosting kills idle workers [files: app/main.py]
D6 order state machine: new, paid, baking, ready, done, cancelled; no other states [files: app/services/orders.py]
D7 times stored in UTC, shown in shop local time (Europe/Kyiv) -- shops share one zone today @c3d4e5f
D8 menu lives in CSV committed under data/menu/, imported on deploy -- owner edits it in a spreadsheet
D9 refunds only via admin panel, never from the bot -- reduces social-engineering risk [files: app/routes/admin.py]
D10 retries use a jobs table polled every 30s, not Celery -- no broker to run [files: app/jobs/retry.py]
D11 config only from environment variables via app/config.py; no .ini or YAML files
D12 i18n with plain dict files per language under app/bot/i18n/ -- gettext was overkill for 120 strings
D13 admin auth is a magic link sent to a Telegram admin chat, no passwords [files: app/routes/admin.py]
D14 every handler is idempotent on update_id -- Telegram redelivers after timeouts @d4e5f6a
D15 prices include VAT and are shown as such; no tax math in code -- owner's accountant confirmed
D16 phone numbers stored hashed with a per-deploy salt; plain number only in the Stripe customer
D17 one deploy target: a single VPS with systemd units in deploy/ -- no containers until a second node
D18 order numbers are per shop and per day, e.g. K-042 -- staff read them aloud at the counter
D19 stock limits are soft: the bot warns but staff can override in admin [files: app/services/stock.py]
D20 feature flags are rows in a flags table, read once per request -- no flag service
D21 logs are JSON lines to stdout, rotated by journald -- no log files written by the app
D22 dependency updates monthly via pip-compile; lock file is requirements.lock, never edit by hand

## REJECTED
X1 SQLAlchemy -- too heavy here; raw SQL in app/db
X2 Celery or RQ for background jobs -- needs Redis; jobs table is enough at this volume
X3 Postgres on a managed host -- costs more than the bakery pays for hosting
X4 storing card data or tokens ourselves -- PCI scope; Stripe Checkout only
X5 separate bot per shop -- three tokens to rotate and users confused which bot to use
X6 Pydantic models in app/db -- double validation; db returns plain dataclasses
X7 websockets for the admin dashboard -- polling every 10s is fine for two admins
X8 a React admin SPA -- server-rendered Jinja pages are enough and need no build step
X9 GraphQL for the admin API -- four endpoints do not justify a schema layer

## RULES
R1 type hints required; use the logger, never print
R2 every SQL statement lives in app/db/*.sql.py helpers; no inline SQL in services
R3 all user-facing strings go through t(key, lang); never hardcode text in handlers
R4 tests never hit the network; use the fakes in tests/fakes/ for Telegram and Stripe
R5 migrations are numbered files in app/db/migrations/; never edit one after it is merged
R6 amounts in logs are cents with currency, e.g. 1250 UAH; never log card or phone data
R7 new env vars must be added to app/config.py and to deploy/env.example in the same commit
R8 run ruff and pytest -q before every commit; CI blocks merges on either

## GOTCHAS
G1 webhook sends duplicate events -- dedupe on event_id [files: app/services/pay.py]
G2 Telegram callback_data max 64 bytes -- store long payloads in callbacks table, pass the row id
G3 SQLite locks under concurrent writes -- keep transactions short; busy_timeout=5000 in conn.py
G4 aiogram 3 filters run in order; the catch-all handler must be registered last [files: app/bot/router.py]
G5 Stripe test clock events arrive out of order -- sort by created before applying
G6 uvicorn --reload double-starts the job poller in dev -- guard with RUN_JOBS=1 env
G7 Kyiv DST switch breaks "orders today" if computed in UTC -- use zoneinfo date in services/time.py
G8 CSV menu import silently drops rows with a BOM in the header -- open with utf-8-sig
G9 Telegram rejects messages over 4096 chars -- long order summaries are split in bot/send.py
G10 httpx default timeout is 5s and Stripe sometimes takes 8s -- pay client sets timeout=15
G11 pytest-asyncio needs asyncio_mode=auto in pyproject or async tests silently pass
G12 systemd restarts the app before SQLite WAL checkpoint finishes -- TimeoutStopSec=20 in deploy/
G13 Windows dev machines check out .sql.py files with CRLF and the hash check fails -- .gitattributes forces LF

## OPEN
Q1 rate limit per user or per IP -- not decided; bot traffic has no IP, so leaning per user
Q2 do pickups need a QR code or is the order number enough -- ask owner after pilot
Q3 keep order history forever or purge after 12 months -- legal answer pending
Q4 one admin role or separate shop-manager role -- depends on whether shops get tablets
Q5 should cancelled orders free stock immediately or after the refund settles
Q6 is a fourth shop in another city planned -- if yes, D7 (single time zone) must change

## NOTES
Owner contact and pilot schedule are in the shared drive, not in this repo.
