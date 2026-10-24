<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: Costanza
stack: python3.10-3.13, Typer, Rich, pytest, ruff, mypy
run: costanza | test: pytest -q
layout: src/costanza (lib), tests, docs/SPEC.md
synced: 661c505 2026-10-24

## NOW
doing: none
done: welcome background, welcome screen, readme polish
next: author says when it is finished
blocked: none

## DECISIONS
D9 review r on a D writes an X entry then accepts -- reject-as-X hybrid; spec r is reject without a file [files: src/costanza/accept.py]
D10 sync asks before writing synced -- user asked for confirm; spec 3.5 says sync never asks [files: src/costanza/sync.py]
D12 W103 skips scan.exclude; files ref valid under root -- globbing hid ledger paths [files: src/costanza/check.py, docs/SPEC.md]
D17 accept needs a human at an interactive terminal with typed confirmation; agents cannot -- stops self-ratification
D18 refuses a foreign post-commit instead of splicing -- deletes only our unmodified file @b34f11d [files: src/costanza/hooks.py]
D29 A, B, and C share one source tree -- B adds the naive handoff, C adds COSTANZA.md [files: bench/PROTOCOL.md]

## REJECTED
X1 parsing claude-code JSONL entries -- the entry format is unpublished and changes between versions [files: src/costanza/importers/claude.py]
X2 A default bench runner that calls a model API -- keep the protocol manual [files: bench/PROTOCOL.md]

## RULES
R1 Never run git push, add a remote, create a GitHub repo, or publish until the author says it is finished. [files: CLAUDE.md]
R4 agent instructions cap an entry at 130 characters -- leaves room under the 160 check
R6 never put bench/keys or scoring notes in a test chat -- the answers would leak into the benchmark [files: bench/make_prompt.py]

## GOTCHAS
G4 proposal after author date, stamp stays -- old commits skip reused ids after an inbox reset @b34f11d [files: src/costanza/hooks.py, docs/SPEC.md]
G5 the 160 warning counts the id, reason and files -- a short text can still overflow
G10 handoff examples are placeholders under a format-only label -- a model treated a sample project as NOW [files: src/costanza/constants.py]
G11 a status reply adds no paste block -- only a real project decision, rejection, rule, gotcha or question [files: src/costanza/constants.py]
G12 Fixture history is built in a temp directory -- nested .git is not this repo [files: bench/make_fixtures.py]

## OPEN
