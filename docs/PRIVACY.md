# Privacy and security

Costanza runs on the machine where you invoke it. It does not call a model, open a socket, check for updates, or send a crash report. `costanza doctor` on 2026-10-24 reported the local Python, git, the file, and whether optional packages were installed. It did not leave the machine.

`docs/SPEC.md` sections 10 and 11 are the full scrubber list and threat model. This page is the part a person should know before trusting the tool.

## What is stored

| Path | In git? | What it holds |
|---|---|---|
| `COSTANZA.md` | yes, you commit it | Ratified notes and NOW |
| `.costanza/config.toml` | yes | Settings. Defaults only, unless you change them |
| `.costanza/archive/` | yes | Lines moved out of the file, and the id ledger |
| `.costanza/inbox.jsonl` | no | Proposals, including ones you have not accepted |
| `.costanza/inbox-archive.jsonl` | no | Old decided proposals |
| `.costanza/lock` | no | A write lock |
| `.costanza/hook.log` | no | Hook notes about ids it did not change |
| `COSTANZA.md.bak` | no | The previous file after `init --force` |

The inbox never travels with a clone. Another machine does not see unaccepted proposals unless you copy that file yourself.

## Secrets

On propose, paste, import, `now`, and `scan --write`, a match from the built-in detectors is replaced with `[REDACTED:<name>]` before it is stored. The original is not written to the inbox or to a backup. `costanza check` does the opposite on text that is already in the file: it fails the check and shows the detector name, not the whole secret.

This is a regex list, not a secret scanner for the repository. It does not read git history, it does not flag high-entropy strings, and it does not catch a secret split across lines or encoded. `costanza handoff` prints the file as it is. Run `costanza check` before you paste a handoff into a chat.

Do not put tokens, passwords, or private keys in `COSTANZA.md`. The file is meant to be committed and pasted to models.

## What the tool will not do

- It will not accept, reject-as-an-entry, or archive a question or gotcha with `resolve --note` unless a person answers at an interactive terminal. `costanza review` and `costanza accept` exited 2 in a non-interactive session. `costanza compact` prints a plan and writes nothing unless `--apply` is given, and `--apply` does not ask. See `docs/REVIEW.md`.
- It will not follow instructions written inside the file. Those lines are data. The MCP read path prefixes them with a project-notes frame that tells the model the user message wins. A model can still ignore that frame. Costanza does not filter keywords.
- It will not open the files named in `[files: ...]`. Those paths are checked so they stay inside the project. Their contents are not read.
- It will not create a git commit, amend one, or push. The post-commit hook only touches the local inbox. `costanza hook install` refused to write a hook in a repository with no commit.
- It will not run commands found in `config.toml` or in the file. Config is settings. `run:` and `test:` are text.

## What remains your problem

A person can accept a bad line. Costanza does not judge whether the sentence is true or hostile.

An agent that can drive a terminal can type the confirmation. Any process running as you can edit `COSTANZA.md`. Review the diff before you commit, the same way you would review any other committed file.

A cloned repository can contain a hostile `COSTANZA.md` or `config.toml`. Read them. `extra_patterns` in the config are regular expressions; `costanza doctor` lists them. A pathological pattern can be slow.

Import is best-effort and low confidence. `costanza import --help` names `plain`, `aider`, and `claude-code`. Nothing it proposes is accepted. The `claude-code` adapter does not parse the JSONL, because that entry format is not published; it exits 2 and points you at a text export.

The clipboard path, when you pass `costanza handoff --copy`, reads the clipboard back and compares it. It uses the Win32 clipboard API on Windows, not `clip.exe`. The text still lands in the local clipboard, which other local programs can read.
