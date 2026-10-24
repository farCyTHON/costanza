# Benchmark

Measured on 2026-10-19 with Python 3.13.5, from the repository root:

```
python bench/measure.py
```

No model was called. The figures below are the command's output, not a guess.

```
Estimator: Costanza estimate (file_tokens in src/costanza/tokens.py).
This is a heuristic, not a BPE tokenizer. On English-heavy text it tends to
overestimate cl100k_base and o200k_base by about 5-20%, and it can underestimate
CJK. These fixtures are English. This run did not compare the heuristic with
tiktoken; that band is the documented expectation, not a measurement from this bench.

Naive handoff: README.md, then a sorted file tree, then the last 20 commits as
YYYY-MM-DD and subject (git log -20 --pretty=format:%aI %s, date taken from the
recorded author time). Short hashes are not included.
Source tree: every file except COSTANZA.md, sorted by path, each prefixed with
a "# path" line, joined with LF. COSTANZA.md is excluded so this column is the
code and README, not the handoff.
A, B, and C each start from that same source text. A is the source alone.
B appends the naive handoff. C appends COSTANZA.md. The parts are joined with LF.

| fixture | COSTANZA.md | naive handoff | source tree | A | B | C |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| till | 294 | 347 | 1861 | 1861 | 2208 | 2155 |
| slip | 294 | 314 | 1104 | 1104 | 1418 | 1398 |

On this run the condition columns add: A equals the source column, B equals source plus naive, and C equals source plus COSTANZA.md.
```

The two `COSTANZA.md` files are not the same text. till is 1,010 characters and slip is 1,015. Both are 29 lines because each is a small CF1 file with the same sections. Seventeen lines are identical boilerplate. Two more differ in wording but have the same per-line estimate. The other ten differ, and those ten sum to 205 on each file, so both totals are 294. The files were not trimmed or padded to the same size. The tie is the heuristic: a line's estimate depends on its character count and its word count, so different sentences of similar length often cost the same.

`bench/fixtures/till` and `bench/fixtures/slip` are the final working trees. They contain no `.git` directory. `python bench/make_fixtures.py` rewrites those trees from `bench/catalog.py`. `python bench/measure.py` rebuilds the 22-commit history in a temporary directory, so a fixture repository cannot be mistaken for this project. Commit subjects are ordinary. The oldest two subjects are outside the last 20.

There is no model runner in this repository. The continuation test is manual.

## Items

Hidden items are seeded and appear only in `COSTANZA.md`. Discoverable items are seeded and appear in the source and in `COSTANZA.md`. Control items are not seeded: the code follows them, and `COSTANZA.md` leaves them out. None of these phrases are in the README or the commit subjects.

### till

- till D1 discoverable (decision): amounts are integer cents. Written in `till/money.py` and `COSTANZA.md`.
- till D2 discoverable (decision): sale ids are S plus six digits. Written in `till/db.py` and `COSTANZA.md`.
- till R1 discoverable (rule): `till/cli.py` does not import sqlite3. Written in `till/cli.py` and `COSTANZA.md`.
- till D3 hidden (decision): never add a database path flag. Written only in `COSTANZA.md`.
- till X1 hidden (rejected): SQLAlchemy. Written only in `COSTANZA.md`.
- till X2 hidden (rejected): FastAPI. Written only in `COSTANZA.md`.
- till G1 hidden (gotcha): a second till process loses sales. Written only in `COSTANZA.md`.
- till C1 control (convention): split totals round half-up. Written in `till/report.py` only.
- till C2 control (convention): sale rows are never deleted. Written in `till/db.py` only.
- till C3 control (convention): bad input exits 2. Written in `till/cli.py` only.

### slip

- slip D1 discoverable (decision): note ids are n plus 8 lowercase hex digits. Written in `src/ids.js` and `COSTANZA.md`.
- slip D2 discoverable (decision): the server listens on 127.0.0.1. Written in `src/server.js` and `COSTANZA.md`.
- slip R1 discoverable (rule): routes never touch the filesystem. Written in `src/routes.js` and `COSTANZA.md`.
- slip D3 hidden (decision): do not add authentication. Written only in `COSTANZA.md`.
- slip X1 hidden (rejected): Express. Written only in `COSTANZA.md`.
- slip X2 hidden (rejected): SQLite. Written only in `COSTANZA.md`.
- slip G1 hidden (gotcha): a crash can leave `notes.json.tmp`. Written only in `COSTANZA.md`.
- slip C1 control (convention): titles longer than 80 characters are rejected. Written in `src/routes.js` only.
- slip C2 control (convention): list order is newest first. Written in `src/store.js` only.
- slip C3 control (convention): responses send `no-store`. Written in `src/server.js` only.

## Protocol

`bench/PROTOCOL.md` is the full procedure. Short version:

Each fixture has five tasks. Each task is run in three fresh chats.

- **A** receives the source tree with `COSTANZA.md` removed.
- **B** receives that same tree plus the naive handoff.
- **C** receives that same tree plus `COSTANZA.md`.

The scorer marks every item followed, missed, or n/a. Hidden and discoverable items are the seeded set. Control items are scored separately and are not added to the seeded counts. The sheet also records contradicted decisions, re-suggested rejections, human corrections, and tool-reported tokens until the first correct answer. Blank means the tool showed no token count, or the answer never became correct. Nobody copies the table above into that column.

`python bench/score.py path/to/results.csv` prints raw counts and `n` for each condition. It prints a percentage only when that condition has at least 30 rows. `bench/results.template.csv` is a header with no data. It is still empty.

`bench/results.csv` is a separate sheet. It has four rows for condition A and four for condition C, all on the till fixture. Condition B has no rows. slip has no scored rows. The model column is Gemini. On 2026-10-24, from the repository root:

```
python bench/score.py bench/results.csv
```

The command exited 0 and printed the report below. It withheld percentages. The counts are raw. This page does not rank A against C, and it does not say that one packet produced a better continuation.

```
# Scores

n is the number of CSV rows in that condition. One row is one task, one condition, one run.
A is the source tree with COSTANZA.md removed. B is that same tree plus the naive handoff.
C is that same tree plus COSTANZA.md.
Hidden and discoverable items are the seeded set. Control items are scored separately
and are not added into the seeded counts.

Rates are shown only for a condition with at least 30 rows. Below that, a percentage looks sharper than these rows can support: the tasks are related, the projects are invented, and a sitting is usually one model.

Models in this file: Gemini.

| condition | n | hidden followed | hidden missed | hidden n/a | discoverable followed | discoverable missed | discoverable n/a | control followed | control missed | control n/a | decisions contradicted | rejected re-suggested | corrections sum | corrections mean | tokens sum | tokens n | tokens mean | reached correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 4 | 2 | 2 | 12 | 3 | 0 | 9 | 2 | 1 | 9 | 1 | 0 | 0 | 0.00 | 0 | 0 | - | 1 |
| B | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | - | 0 |
| C | 4 | 3 | 1 | 12 | 2 | 0 | 10 | 1 | 0 | 11 | 1 | 0 | 0 | 0.00 | 0 | 0 | - | 2 |

Percentages withheld for: A (n=4), B (n=0), C (n=4).

## Per item

| condition | fixture | item | kind | followed | missed | n/a |
| --- | --- | --- | --- | --- | --- | --- |
| A | till | D1 | discoverable | 1 | 0 | 3 |
| A | till | D2 | discoverable | 1 | 0 | 3 |
| A | till | R1 | discoverable | 1 | 0 | 3 |
| A | till | D3 | hidden | 0 | 1 | 3 |
| A | till | X1 | hidden | 1 | 0 | 3 |
| A | till | X2 | hidden | 1 | 0 | 3 |
| A | till | G1 | hidden | 0 | 1 | 3 |
| A | till | C1 | control | 0 | 0 | 4 |
| A | till | C2 | control | 1 | 0 | 3 |
| A | till | C3 | control | 1 | 1 | 2 |
| C | till | D1 | discoverable | 1 | 0 | 3 |
| C | till | D2 | discoverable | 0 | 0 | 4 |
| C | till | R1 | discoverable | 1 | 0 | 3 |
| C | till | D3 | hidden | 0 | 1 | 3 |
| C | till | X1 | hidden | 1 | 0 | 3 |
| C | till | X2 | hidden | 1 | 0 | 3 |
| C | till | G1 | hidden | 1 | 0 | 3 |
| C | till | C1 | control | 0 | 0 | 4 |
| C | till | C2 | control | 1 | 0 | 3 |
| C | till | C3 | control | 0 | 0 | 4 |
```

Do not type new numbers into this report. Re-run the command if the sheet changes.

## Limitations

- **Small sample.** The sheet above is four A rows and four C rows, one model, one invented project. A full pass of this protocol is 30 rows for one model, and `score.py` still treats that as the minimum before it will print a percentage. The tasks share a fixture, so those rows are not independent samples.
- **Invented projects.** till and slip are small fiction. They are not a production codebase, and a result here does not measure a real handoff.
- **One model.** Nothing in this file is a model result. A person who runs the protocol uses whatever tool they have, usually one model per sheet. A sheet that mixes models says so, and its means are not one model's score.
- **Estimator error.** The counts use Costanza's `estimate` heuristic. On English-heavy text it tends to sit about 5-20% above `cl100k_base` and `o200k_base`, and it can underestimate CJK. These fixtures are English. This bench did not run tiktoken, so that band is the documented expectation of the heuristic, not an error measured here.
- **Control items.** Each fixture follows a few conventions that `COSTANZA.md` deliberately does not mention. They are scored in their own columns. A, B, and C all receive the source, so all three can read the controls. The file adds no control text. A control score for C that is higher than A's means C did something the file does not say.
- **Hidden versus discoverable.** Hidden items are absent from the source, the README, and the commit subjects. Only C is given those sentences, because only C receives `COSTANZA.md`. Discoverable items are in the source as well as in `COSTANZA.md`, so the fixture is not a list of facts that exist only in the handoff. A and B can find them by reading the tree. C can read them and is also told. The labels above say which items are which.
