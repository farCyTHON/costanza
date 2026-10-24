# The file

`COSTANZA.md` is Costanza Format v1. `docs/SPEC.md` is the full grammar. This page is the shape a person needs, checked against the commands below on 2026-10-24. Where a command and the spec disagree, the command is what ran.

## Layout

`costanza init --name "sample" --agents none` wrote this skeleton (the token line on that run was `~94 tokens`):

```
<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: sample
stack: ?
run: ? | test: ?
layout: ?
synced: never

## NOW
doing: none
done: none
next: none
blocked: none

## DECISIONS

## REJECTED

## RULES

## GOTCHAS

## OPEN
```

The first line is the version marker. Line 2 is the project. The header keys are `stack`, `run`, `test`, `layout`, and `synced`. `?` means unknown. `synced: never` means the file has not been pointed at a commit.

NOW is four lines: `doing`, `done`, `next`, `blocked`. `none` means empty. NOW is written directly by `costanza now` and by `now` lines in a paste. The other sections are not.

| Section | Id | What the line is |
|---|---|---|
| DECISIONS | D | A decision, with an optional reason |
| REJECTED | X | An idea that was ruled out. A reason is required |
| RULES | R | A rule |
| GOTCHAS | G | A surprise, and optionally the workaround |
| OPEN | Q | A question that is still open |

An entry is one line:

```
D1 one handoff file at the repo root -- a new chat can read it
```

The reason, when present, follows ` -- `. A commit can be attached as `@` and a 7 to 12 character hex id. File pointers, when present, are `[files: path]`, repo-relative, with no `..` and no absolute path. Ids start at 1 and are not reused, including after a line is archived or deleted by hand. The high-water mark is `.costanza/archive/ids`.

A heading Costanza does not know, such as `## NOTES`, is kept as it was. It is not rewritten into an entry.

## Budget

The default ceiling is 1,800. The count is an estimate from `src/costanza/tokens.py` unless `budget.tokenizer` is `tiktoken` and a local cache is already present. The status line marks an estimate with `~`. Costanza does not download encoding files.

`costanza compact` prints a plan and writes nothing. `costanza compact --help` says `--apply` is "Write the plan (default is dry-run)." On the fresh sample, `costanza compact` printed `· nothing to compact (94 / 1,800; target 1,530 = 85% of 1,800)`.

Lines that `compact --apply` moves are appended under `.costanza/archive/`. There is no restore command. Copy a line back by hand if you still want it in the file.

## Check

`costanza check` reads the file and prints findings. It does not edit it. On the sample, after NOW had been updated, it printed four warnings and exited 0:

```
! CF017  line 2: header layout is '?'; replace it with the real value or leave it for cz scan
! CF017  line 2: header run is '?'; replace it with the real value or leave it for cz scan
! CF017  line 2: header stack is '?'; replace it with the real value or leave it for cz scan
! CF017  line 2: header test is '?'; replace it with the real value or leave it for cz scan
· 0 errors, 4 warnings
```

`costanza check --strict` on that same file exited 3. `docs/SPEC.md` names this `?` header warning CF017.

`costanza scan` and `costanza scan --write` on a sample with no manifest both printed `· header already matches the repo` and exited 0.
