# Review

An agent proposes. A person accepts. Until then the line is only in `.costanza/inbox.jsonl`, which git ignores.

## Propose

These commands append a proposal and do not change `DECISIONS`, `REJECTED`, `RULES`, `GOTCHAS`, or `OPEN`:

```
costanza decide "one handoff file at the repo root -- a new chat can read it"
costanza reject "a second handoff file -- one file is the point"
costanza rule "read COSTANZA.md before editing"
costanza gotcha "the inbox is local -- it is not in git"
costanza ask "which header values are still unknown"
costanza propose D "one handoff file at the repo root"
```

`decide` is kind D, `reject` is X, `rule` is R, `gotcha` is G, and `ask` is Q. `reject` requires a reason, either after ` -- ` or as `--why`. On 2026-10-24 those five commands after `decide` were run in that order. `reject`, `rule`, `gotcha`, and `ask` each printed a new proposal (`p3` through `p6`). The `propose` line repeats the decision text, so it printed `· duplicate of p1` and exited 0. The decide command printed:

```
✓ p1 proposed  D  one handoff file at the repo root
next: cz review
```

`costanza list` printed:

```
p1  D  proposed  cli  2026-10-24  one handoff file at the repo root
```

`costanza now` updates NOW directly. It does not go through the inbox. With no flags it prints NOW and writes nothing. After a paste that contained `now doing: write the first note`, `costanza now` printed:

```
  doing: write the first note
  done: none
  next: none
  blocked: none
```

## Paste

`costanza paste --file reply.md` reads a file. A bare file is accepted when every non-blank line parses. This file worked:

```
decide: keep the handoff in the repo root -- a new chat can read it
now doing: write the first note
```

The run printed `✓ p2 proposed`, `✓ NOW doing`, and `✓ 1 proposed, NOW updated (doing)`. The `now` line was written into the file. The `decide` line was only proposed. `costanza paste --help` also lists `--clipboard`, `--dry-run`, and `--partial`.

## Review and accept

`costanza review` needs an interactive terminal. From this session it exited 2:

```
review needs an interactive terminal
next: run cz review in your own terminal (cz dismiss <id> works from scripts)
```

`costanza accept p1` from the same session exited 2:

```
accept needs a person at an interactive terminal
next: run cz review in your own terminal
```

In a terminal, `costanza review` reads one key at a time. The program's prompt is `[a]ccept  [r]eject  [d]ismiss  [e]dit  [s]kip  [q]uit`. `?` prints that list again.

| Key | Effect |
|---|---|
| `a` | Accept this proposal into `COSTANZA.md`. The keypress is the confirmation. |
| `r` | On a decision, write an X entry (a rejected idea) and accept that. On any other kind, mark the proposal rejected and do not change the file. |
| `d` | Dismiss. The file is unchanged. |
| `e` | Edit text, reason, and files, then confirm the edit. |
| `s` | Skip. |
| `q` | Stop. Decisions already made are kept. |

The X-on-`r` behavior for a decision is what the program does. `docs/SPEC.md` describes `r` as a reject that does not write the file. `COSTANZA.md` records the program's behavior as D9.

`costanza accept p1` in a terminal lists the line it would write and asks `accept N proposals into COSTANZA.md? [y/N]`. Any answer other than yes writes nothing and exits 0. There is no `--yes` on `accept`.

`costanza dismiss` does not need a terminal, because it does not change ratified text. On the sample, `costanza dismiss p2` printed `✓ p2 dismissed`.

`costanza resolve Q1 --note "closed"` and `costanza resolve Q1 --decide "keep one file -- closed"` on the sample, which has no Q1, both exited 2 and printed the same error: `Q1 is not a Q or G entry in COSTANZA.md`, then `next: cz status`. Neither edited the file, and `--decide` did not propose a line. `docs/SPEC.md` says the id has to be a Q or G entry in the file.

## What "accepted" means

Accepted means a person was at an interactive terminal and confirmed the write. A commit trailer `Costanza-Accept` only marks the proposal as suggested so review shows it first. The MCP server has no accept tool. No flag, environment variable, or config key skips the question.

A program that can type into your terminal can still answer yes. Anything running as you can edit `COSTANZA.md` directly. The gate is there to stop an unattended accept, not to stop the account owner.
