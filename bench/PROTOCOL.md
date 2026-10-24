# Benchmark protocol

This is a manual experiment. The repository does not call a model. Do not paste this file, `bench/keys/`, or `docs/BENCHMARK.md` into the agent. Those files are the answer key.

Do not invent token counts. If the tool does not show a token total, leave the cell blank. Do not copy the table from `python bench/measure.py` into the CSV. That table is the size of the packet under Costanza's heuristic, not the tokens a chat used.

## Packets

From the repository root:

```
python bench/measure.py --packets bench/generated
```

That command rebuilds each fixture's git history in a temporary directory. It does not call a model. It writes three folders per fixture. The source files match. `COSTANZA.md` is not in that shared tree.

| Condition | till | slip | Extra file |
| --- | --- | --- | --- |
| A | `bench/generated/till/A/` | `bench/generated/slip/A/` | none |
| B | `bench/generated/till/B/` | `bench/generated/slip/B/` | `NAIVE.md` |
| C | `bench/generated/till/C/` | `bench/generated/slip/C/` | `COSTANZA.md` |

`bench/generated/` is gitignored. Rebuild it when you run the experiment so `NAIVE.md` matches the measured naive handoff.

## Conditions

Use one fresh chat per row. Do not carry a chat from one condition into another. Paste the same task text every time. The files below are what that paste contains.

- **A.** The folder `A/`. Source only. No handoff file.
- **B.** The folder `B/`. The same source, plus `NAIVE.md` (README, file tree, and the last 20 commit dates and subjects).
- **C.** The folder `C/`. The same source, plus `COSTANZA.md`.

All three see the same code. The handoff is the only difference. Discoverable items and control items are in that code. Hidden items are stated only in `COSTANZA.md`, so only C is given those sentences. Control items are scored separately: the file does not mention them, so a higher control score for C is not the file repeating itself.

## Fresh chat

Print the paste for one row. It is the condition's files, then the task wording from the list below. It does not include `bench/keys/` or the scoring notes.

```
python bench/make_prompt.py till A 1
```

The arguments are the fixture (`till` or `slip`), the condition (`A`, `B`, or `C`), and the task number. Task 1 is the first task under that fixture. Paste the output into a fresh chat.

## Item kinds

Score the three kinds separately. Do not add control counts to seeded counts when you talk about whether the handoff helped.

| Kind | Where it is written | What a high score means |
| --- | --- | --- |
| Hidden | `COSTANZA.md` only. Not in the source, the README, or the commit subjects. | C was told. A and B have the code, which does not state it. |
| Discoverable | Source and `COSTANZA.md`. Not in the README or the commit subjects. | All three can read it in the source. C is also told. |
| Control | Source only. Omitted from `COSTANZA.md` on purpose. | All three can read it. C's file does not mention it. Control items are scored separately. |

Hidden and discoverable items are the seeded set. Control items are not seeded. They exist so a high score for C on hidden items, next to a control score no higher than A, means the file added something the code does not say. A higher control score for C means C did something the file does not say.

### till

| id | kind | type | what the scorer checks |
| --- | --- | --- | --- |
| D1 | discoverable | decision | Amounts are integer cents; do not float a drawer amount. |
| D2 | discoverable | decision | Sale ids are S plus six digits from a counter. |
| R1 | discoverable | rule | till/cli.py does not import sqlite3. |
| D3 | hidden | decision | Never add a database path flag. |
| X1 | hidden | rejected | Do not bring in SQLAlchemy. |
| X2 | hidden | rejected | Do not add a FastAPI admin page. |
| G1 | hidden | gotcha | A second till process on one drawer file loses sales. |
| C1 | control | convention | Split totals round half-up. |
| C2 | control | convention | Sale rows are never deleted. |
| C3 | control | convention | Bad input exits 2. |

### slip

| id | kind | type | what the scorer checks |
| --- | --- | --- | --- |
| D1 | discoverable | decision | Note ids are n plus 8 lowercase hex digits. |
| D2 | discoverable | decision | The server listens on 127.0.0.1. |
| R1 | discoverable | rule | Routes never touch the filesystem. |
| D3 | hidden | decision | do not add authentication; the loopback bind is the only guard |
| X1 | hidden | rejected | Do not use Express. |
| X2 | hidden | rejected | Do not use SQLite. |
| G1 | hidden | gotcha | A crash can leave data/notes.json.tmp behind. |
| C1 | control | convention | Titles are rejected when empty or longer than 80 characters. |
| C2 | control | convention | List order is newest first. |
| C3 | control | convention | Responses send cache-control no-store. |

## How to mark a row

`item_results` lists every item for that fixture, separated by semicolons: `D1=1;D2=0;D3=`.

- `1` means followed.
- `0` means missed.
- empty after `=` means n/a.

For a decision, rule, gotcha, or control convention, followed means the answer obeys it. For a rejected idea, followed means the answer does not propose that idea again. Missed means the opposite: a decision was contradicted, or a rejected idea was re-suggested.

Start from the applicable list under the task. Leave every other item empty. If the answer also breaks an item that was not applicable, change that item from empty to `0`.

`score.py` counts contradicted decisions and re-suggested rejections from those marks. Do not add your own totals for them.

`human_corrections` is the number of messages you send after the first answer. The opening task does not count. If the first answer is already correct, write `0`. Do not quote this protocol, the answer key, or an item sentence in a correction. Point at a concrete failure in the answer.

`reached_correct` is `1` only when every applicable item is followed and you would accept the answer. Otherwise `0`. If you stop before that, `item_results` describes the last answer.

`tokens_to_first_correct` is the token total the tool reports for the chat through the first correct answer, including the packet you pasted. Fill it only when `reached_correct` is `1` and the tool showed a number. If the run never became correct, or the tool shows no token count, leave the cell blank. Do not estimate.

One CSV may cover both fixtures. Use condition names `A`, `B`, and `C`. The `packet` cell must be `source` for A, `source+naive` for B, and `source+costanza` for C. Put the model name in `model` and a run number in `run`. Five tasks times two fixtures times three conditions is 30 rows for one model, one pass. That is the smallest file for which `score.py` will print a percentage, and even then the tasks are not independent samples.

## Tasks

`make_prompt.py` prints the task line below after the condition's files. Do not paste the applicable list.

### till

**refund.** Add a refund.

Task: Add a refund command. It records money going back to the customer for one existing sale. Stay consistent with how this project already stores money and names sales.

Applicable: D1, D2, R1, X1, C2, C3

**path.** Choose a drawer file.

Task: A second shop will use the same program. Add a command-line option that chooses where the drawer file is stored.

Applicable: D3

**admin.** Browser view.

Task: The owner wants to look at today's sales in a browser. Add that view.

Applicable: X2

**average.** Average sale.

Task: The daily report should also show the average sale.

Applicable: D1, C1

**share.** Two clerks.

Task: Two clerks need to record sales at the same moment on the same drawer. Make that safe.

Applicable: G1

### slip

**search.** Find a note.

Task: Add a way to find notes whose title contains a word the caller typed.

Applicable: D1, R1, C1, C2, C3

**login.** Separate accounts.

Task: Add accounts so each person sees only the notes they created.

Applicable: D3

**database.** Replace the JSON file.

Task: Replace the JSON file with an embedded SQL library or a database server.

Applicable: X2

**retitle.** Change a title.

Task: Add a way to change a note's title after it is created.

Applicable: D1, R1, C1

**phone.** Reach it from a phone.

Task: Make the server reachable from a phone on the same Wi-Fi.

Applicable: D2

## Results CSV

Copy `bench/results.template.csv`. Do not score the template; it has no data rows. Columns:

```
fixture,task,condition,packet,model,run,item_results,human_corrections,tokens_to_first_correct,reached_correct,notes
```

`notes` is optional. The example below is not a measurement. Do not leave it in a file you score.

```
till,refund,C,source+costanza,example-model,1,D1=1;D2=1;R1=1;D3=;X1=1;X2=;G1=;C1=;C2=0;C3=1,0,800,1,example only
```

Aggregate a file you actually filled:

```
python bench/score.py path/to/results.csv
```

The report always prints raw counts and `n` for conditions A, B, and C. `n` is rows, not items. It prints a percentage only when that condition has at least 30 rows. Below 30, a percentage looks sharper than these rows can support: the tasks are related, the projects are invented, and a sitting is usually one model. Control percentages, when shown, stay in their own column.
