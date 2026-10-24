# Roadmap

## v0.1

The local program in this repository, version 0.1.0. It is not published.

Included: one `COSTANZA.md`, the inbox, review by a person, handoff and paste, agent instruction blocks, the git hook, the stdio MCP server, import, and doctor. The benchmark protocol is included. `bench/results.csv` is a preliminary sheet: four rows for condition A, four for condition C, none for B, one model, invented projects.

## Not in v0.1

- A PyPI release. The name was unused on 2026-10-24. Publishing waits until the author says the project is finished. See `docs/RELEASING.md`.
- Watching a chat, a restore command, or any model call.
- A benchmark rate. `python bench/score.py` prints a percentage only when a condition has at least 30 rows. This sheet does not.

## Later

Only after the author says the project is finished:

- Publish the 0.1.0 distributions with `.github/workflows/publish-pypi.yml`.
- Replace the Homepage URL in `pyproject.toml`. This clone has no git remote, and the current URL is a placeholder.

## Not planned

These are non-goals, not deferred features: model calls, network access, telemetry, a web UI, automatic commits, scanning the source tree for secrets, and more than one `COSTANZA.md` per repository.

A parser for Claude Code JSONL transcripts is rejected. The entry format is unpublished. A benchmark runner that calls a model API is rejected. The protocol stays manual.
