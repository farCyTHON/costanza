
# Costanza

Costanza keeps one small file, `COSTANZA.md`, so the next AI chat can continue a project without re-reading the repository or trusting an unreviewed summary.

Costanza is local. It does not call a model, open a network connection, or send telemetry.

## The problem

A free AI chat runs out of context, and the next account or the next model starts blank. The code and the git history do not record why a decision was made, what was rejected, or what is in progress. Writing that briefing again spends the tokens the new chat needed for the work.

## What the file looks like

The opening of `bench/fixtures/slip/COSTANZA.md`:

```
<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: slip, local note inbox
stack: node, no dependencies
run: node src/server.js
layout: src/server.js (http), src/routes.js (handlers), src/store.js (files), src/ids.js (ids)
synced: local 2026-01-27

## NOW
```

## 30-second demo

From a new directory:

```
git init
costanza init --name "sample" --agents none
costanza decide "one handoff file at the repo root -- a new chat can read it"
costanza status
costanza list
costanza handoff --with-inbox
```

`demo/demo.sh` runs those commands in a fresh temporary project.

[terminal recording: not recorded yet. Capture `sh demo/demo.sh`.]

The decision stays in the inbox because accept needs a person at an interactive terminal.

## Install

Python 3.10, 3.11, 3.12, or 3.13. The commands are `costanza` and `cz`.

The package is not on PyPI. Install from a checkout:

```
pipx install .
python -m pip install .
```

The MCP server and the optional tokenizer are extras: `costanza[mcp]` and `costanza[tokens]`. Costanza does not download a tokenizer. If you set `tokenizer = "tiktoken"`, seed the cache yourself. Otherwise it keeps using its built-in estimate.

## Five-minute quickstart

In a new git directory:

```
git init
costanza init --name "sample" --agents none
costanza agents install
costanza decide "one handoff file at the repo root -- a new chat can read it"
costanza list
costanza review
costanza handoff --for chat
```

Write `reply.md` as UTF-8 without a BOM:

```
decide: keep the handoff in the repo root -- a new chat can read it
now doing: write the first note
```

```
costanza paste --file reply.md
```

What those commands do:

- `costanza init` creates `COSTANZA.md`, `.costanza/config.toml`, and `.costanza/archive/ids`, and updates `.gitignore`.
- `costanza agents install` creates `AGENTS.md` when that file is not already there.
- `costanza decide` proposes a decision and prints `next: cz review`. It does not write the decision into `COSTANZA.md`.
- `costanza review` and `costanza accept` need an interactive terminal. Without one, both exit 2. Review says `review needs an interactive terminal`. Accept says `accept needs a person at an interactive terminal`.
- In your own terminal, `costanza review` walks the inbox. `a` accepts, `r` rejects, `d` dismisses, `e` edits, `s` skips, `q` quits, and `?` prints the keys. On a decision, `r` writes an X entry. On any other kind, `r` only marks the proposal rejected.
- `costanza handoff --for chat` prints a preamble, the file, and a paste-block reminder.
- `costanza paste --file reply.md` writes `now` lines immediately. A `decide` line stays a proposal.

`costanza dismiss` does not change the decision sections.

## Commands

`costanza --help` lists these 27 commands:

| Command | Summary |
|---|---|
| `init` | Create `COSTANZA.md` and `.costanza/` in this project. |
| `status` | Show the project summary and token budget. |
| `decide` | Propose a decision. |
| `reject` | Propose a rejected idea. |
| `rule` | Propose a rule. |
| `gotcha` | Propose a gotcha. |
| `ask` | Propose an open question. |
| `now` | Update the NOW block. |
| `propose` | Propose an entry of any kind. |
| `list` | List inbox proposals. |
| `review` | Review proposed entries interactively. |
| `accept` | Accept proposals into `COSTANZA.md`. |
| `dismiss` | Dismiss or reject a proposal. |
| `resolve` | Archive a resolved question or gotcha. |
| `paste` | Apply a costanza paste block. |
| `handoff` | Print a handoff packet for a new chat. |
| `prompt` | Print the one-sentence bootstrap for tools that can read `COSTANZA.md`. |
| `scan` | Detect header facts from the repo. |
| `check` | Validate `COSTANZA.md`. |
| `compact` | Move overflow entries to the archive. |
| `sync` | Update the synced commit pointer. |
| `mcp` | Run the MCP server on stdio. |
| `import` | Import session notes as proposals. Best-effort; nothing is accepted. |
| `doctor` | Check the Costanza installation. |
| `agents` | Install or remove agent instruction blocks. |
| `hook` | Install or remove the git post-commit hook. |
| `welcome` | Print the welcome screen. |

`costanza hook uninstall` is the same action as `costanza hook remove`. Global options are `--root`, `--quiet` / `-q`, and `--no-color`. `--version` prints the version and exits 0.

## Shell agents

`costanza agents install` writes a marked block into agent instruction files. With the default mode, `auto`, it creates `AGENTS.md`. It updates `CLAUDE.md`, `GEMINI.md`, and `.github/copilot-instructions.md` when those files already exist. It creates `.cursor/rules/costanza.mdc` when `.cursor/` exists. `--mode all` creates the default targets. `--mode none` writes none. `costanza init --agents` takes the same three modes.

The block tells the agent to read `COSTANZA.md`, obey it, and propose changes instead of editing the decision sections. Text outside the markers is left as it is.

`costanza hook install` writes a post-commit hook once the repository has a commit. On the sample, which had `git init` and no commit, it exited 2 and printed `needs a git repo with at least one commit (git init is enough, no remote needed)`. The hook stamps proposed lines that have no commit yet. A `Costanza-Accept` trailer marks a proposal as suggested for review. A `Costanza-Reject` trailer rejects that proposal in the inbox. It never accepts an entry and it never creates a commit. `costanza hook run` exits 0 even when it skips work, so a commit is not blocked.

## MCP clients

`costanza mcp` speaks MCP over stdio. The tools are `costanza_read`, `costanza_propose`, and `costanza_now`. There is no accept tool. Setup for each client is `costanza mcp --print-config`, documented in `docs/MCP.md` from the command's own output. The extra is `costanza[mcp]`. Without it, `costanza mcp` exits 1 and names `pip install "costanza[mcp]"`. `--print-config` does not need the extra.

## Chat-only tools

`costanza handoff --for chat` prints text you can paste into a chat that has no tools. `costanza prompt` prints one sentence for a tool that can already read the file. `costanza paste` reads a fenced block, or a file whose every line is already a paste line, and turns it into proposals. `now` lines are the exception: they update the NOW block directly. `costanza import` can propose lines from a saved `plain` or `aider` transcript. It previews unless you pass `--yes`, and it still does not accept. `claude-code` is refused: the entry format is not a published schema, so the command tells you to export text and use `plain`.

## How this differs

**AGENTS.md and CLAUDE.md files.** Those files are standing instructions for a tool. Costanza can insert a short block into them. The block is not the project memory. `COSTANZA.md` is the memory: decisions, rejected ideas, rules, gotchas, open questions, and the NOW lines. It has an inbox, and a person accepts each entry. An instruction file does not.

**Repo-packing tools.** A packer puts source files into a context window so a model can read the code. Costanza does not pack the repository and does not replace that. It stores the sentences the code and the git history do not contain. A packer is for the source. Costanza is for the ratified notes.

**Asking the AI for a summary.** A summary lives in that chat. Nobody has accepted it, it has no id, and the next account does not have it unless someone copies it. Costanza keeps one file in the repository. Each accepted line was proposed, then confirmed by a person. The next chat reads the file instead of a fresh summary.

## Limits

Costanza cannot watch a chat. Nothing is recorded unless you run a command, paste a block, import a saved file, or an MCP client calls a tool.

Accepted means a person reviewed it. `costanza accept`, `costanza review`, and the other authoritative writes ask at an interactive terminal. No flag, environment variable, or config key skips that. `Costanza-Accept` in a commit message only marks a proposal as suggested. MCP cannot accept. That stops an accidental accept. It does not stop a determined one: a program that can type into a terminal can answer yes, and any process running as you can edit `COSTANZA.md`. A wrong line is fixed by editing that line. The id is not issued again.

Token counts are an estimate. The default estimator is a heuristic. The `~` on the status line means estimate. It is not a count from the model you are talking to.

There is no restore command. `costanza compact --apply` and `costanza resolve` append lines under `.costanza/archive/`. Putting a line back means copying it into `COSTANZA.md` by hand.

`costanza compact` without `--apply` only prints a plan. `costanza sync` in a repository with no commit exits 2 and prints `needs a git repo with at least one commit (git init is enough, no remote needed)`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success, including a declined confirmation. |
| 1 | Error, such as a missing file or a bad id. |
| 2 | Usage. This includes `review` and `accept` with no interactive terminal. |
| 3 | `check --strict` or `doctor` found a problem. `check` with warnings and no `--strict` exits 0. |
| 130 | Ctrl+C. The line is `cancelled`. |

On the sample project, `costanza check` exited 0 with four `CF017` warnings for `?` header values. `costanza check --strict` exited 3 on those warnings.

## FAQ

**Does it upload the file?** No. There is no network call in the tool.

**Can the agent accept its own proposal?** Not through Costanza. It can propose. You accept in a terminal.

**What do I commit?** `COSTANZA.md`, `.costanza/config.toml`, and `.costanza/archive/`. The inbox, the lock, and backups are gitignored.

**Why is the header full of question marks?** `init` writes `?` for header values it does not have. On a sample with no manifest, `costanza scan` and `costanza scan --write` both printed `· header already matches the repo` and exited 0. Edit the header in `COSTANZA.md` when you know the real values.

**Where did an old entry go?** `.costanza/archive/`. There is no restore command.

**Is the PyPI package live?** No. See `docs/RELEASING.md`.

## Docs

- `docs/FORMAT.md` — the file
- `docs/REVIEW.md` — propose, review, accept
- `docs/PRIVACY.md` — what stays on the machine
- `docs/MCP.md` — client setup, quoted from `costanza mcp --print-config`
- `docs/BENCHMARK.md` — how the packet sizes and the preliminary sheet were measured
- `docs/SPEC.md` — the full specification
- `docs/RELEASING.md` — the release checklist

## Benchmark

The method is in `docs/BENCHMARK.md`. Condition A is the source tree. Condition B adds a naive handoff. Condition C adds `COSTANZA.md`. The projects are invented. A preliminary sheet, `bench/results.csv`, has four rows for A and four rows for C, and no rows for B. The model column names one model. `python bench/score.py bench/results.csv` printed raw counts and withheld rates. This README does not claim that Costanza changes those continuations.

## License

MIT. See `LICENSE`. Fardin Hasan Siam
