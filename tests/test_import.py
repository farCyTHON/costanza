"""Transcript import: plain text, Aider history, and the Claude Code refusal."""

from __future__ import annotations

from pathlib import Path

from costanza.inbox import load_inbox
from costanza.paths import ProjectPaths
from tests.helpers import InvokeFn

FIXTURES = Path(__file__).parent / "fixtures" / "import"


def _root(invoke: InvokeFn, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    result = invoke(["--root", str(root), "init"])
    assert result.exit_code == 0, result.stdout + result.stderr
    return root


def _import(invoke: InvokeFn, root: Path, source: str, path: Path, *extra: str) -> object:
    return invoke(["--root", str(root), "import", source, str(path), *extra])


def test_plain_normal_previews_and_yes_writes(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _root(invoke, tmp_path)
    path = FIXTURES / "plain-normal.md"
    preview = _import(invoke, root, "plain", path)
    assert preview.exit_code == 0, preview.stdout + preview.stderr
    assert "4 candidates" in preview.stdout
    assert "low confidence" in preview.stdout
    assert "nothing written" in preview.stdout
    assert "keep orders in one sqlite file" in preview.stdout
    assert "type hints on every function" in preview.stdout
    assert "webhook fires twice" in preview.stdout
    assert "per user or per ip?" in preview.stdout
    assert not (root / ".costanza" / "inbox.jsonl").exists()

    written = _import(invoke, root, "plain", path, "--yes")
    assert written.exit_code == 0, written.stdout + written.stderr
    assert "4 proposed" in written.stdout
    handoff = (root / "COSTANZA.md").read_text(encoding="utf-8")
    assert "keep orders in one sqlite file" not in handoff
    stored = load_inbox(ProjectPaths(root).inbox).proposed()
    assert [item.kind for item in stored] == ["D", "R", "G", "Q"]
    assert {item.source for item in stored} == {"import"}
    assert {item.agent for item in stored} == {"plain"}
    assert {item.extra.get("confidence") for item in stored} == {"low"}

    again = _import(invoke, root, "plain", path, "--yes")
    assert again.exit_code == 0, again.stdout + again.stderr
    assert "0 proposed, 4 duplicate" in again.stdout
    assert len(load_inbox(ProjectPaths(root).inbox).proposed()) == 4


def test_plain_empty_truncated_and_malformed(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _root(invoke, tmp_path)
    empty = _import(invoke, root, "plain", FIXTURES / "plain-empty.md")
    assert empty.exit_code == 0, empty.stdout + empty.stderr
    assert "0 candidates" in empty.stdout
    assert "nothing written" in empty.stdout

    truncated = _import(invoke, root, "plain", FIXTURES / "plain-truncated.md")
    assert truncated.exit_code == 0, truncated.stdout + truncated.stderr
    assert "1 candidates" in truncated.stdout
    assert "ship the notes with the repo" in truncated.stdout
    assert "unclosed fence" not in truncated.stdout
    assert "open block" in truncated.stderr

    malformed = _import(invoke, root, "plain", FIXTURES / "plain-malformed.md")
    assert malformed.exit_code == 0, malformed.stdout + malformed.stderr
    assert "2 candidates, 2 skipped" in malformed.stdout
    assert "keep lines short" in malformed.stdout
    assert "clocks drift" in malformed.stdout
    assert "decide without a colon" not in malformed.stdout
    assert not (root / ".costanza" / "inbox.jsonl").exists()


def test_aider_reads_messages_and_skips_tools_and_diffs(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _root(invoke, tmp_path)
    normal = _import(invoke, root, "aider", FIXTURES / "aider-normal.md")
    blob = normal.stdout + normal.stderr
    assert normal.exit_code == 0, blob
    assert "3 candidates" in normal.stdout
    assert "keep the notes in one markdown file" in normal.stdout
    assert "never send the notes" in normal.stdout
    assert "one file or a folder?" in normal.stdout
    assert "tool line must not" not in blob
    assert "diff line must not" not in blob
    assert "Applied edit" not in blob

    empty = _import(invoke, root, "aider", FIXTURES / "aider-empty.md")
    assert empty.exit_code == 0, empty.stdout + empty.stderr
    assert "0 candidates" in empty.stdout

    truncated = _import(invoke, root, "aider", FIXTURES / "aider-truncated.md")
    assert truncated.exit_code == 0, truncated.stdout + truncated.stderr
    assert "1 candidates" in truncated.stdout
    assert "keep a backup" in truncated.stdout
    assert "unfinished diff" not in (truncated.stdout + truncated.stderr)
    assert "open block" in truncated.stderr

    malformed = _import(invoke, root, "aider", FIXTURES / "aider-malformed.md")
    assert malformed.exit_code == 0, malformed.stdout + malformed.stderr
    assert "1 candidates, 1 skipped" in malformed.stdout
    assert "clock drifts" in malformed.stdout


def test_claude_code_is_not_guessed(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _root(invoke, tmp_path)
    path = FIXTURES / "claude-unverified.jsonl"
    secret = "ghp_" + ("a" * 36)
    assert secret in path.read_text(encoding="utf-8")
    result = _import(invoke, root, "claude-code", path)
    blob = result.stdout + result.stderr
    assert result.exit_code == 2, blob
    assert "unpublished" in blob
    assert "code.claude.com/docs/en/sessions" in blob
    assert "best-effort" in blob
    assert secret not in blob
    assert "do not parse this file" not in blob
    assert not (root / ".costanza" / "inbox.jsonl").exists()


def test_scrubber_size_limit_and_bad_bytes(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _root(invoke, tmp_path)
    secret = "ghp_" + ("b" * 36)
    notes = tmp_path / "notes.md"
    notes.write_text(
        f"Decision: the token {secret} was rotated -- rotate it\n",
        encoding="utf-8",
    )
    preview = _import(invoke, root, "plain", notes)
    assert secret not in (preview.stdout + preview.stderr)
    assert "[REDACTED:github_token]" in preview.stdout

    written = _import(invoke, root, "plain", notes, "--yes")
    assert written.exit_code == 0, written.stdout + written.stderr
    stored = load_inbox(ProjectPaths(root).inbox).proposed()
    assert len(stored) == 1
    assert secret not in stored[0].text
    assert "[REDACTED:github_token]" in stored[0].text
    assert "github_token" in stored[0].extra or "github_token" in written.stderr

    config = root / ".costanza" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("max_bytes = 1048576", "max_bytes = 1024"),
        encoding="utf-8",
    )
    huge = tmp_path / "huge.md"
    huge.write_text("Decision: too big to read -- skip the file\n" * 40, encoding="utf-8")
    skipped = _import(invoke, root, "plain", huge)
    assert skipped.exit_code == 1, skipped.stdout + skipped.stderr
    assert "import.max_bytes" in (skipped.stdout + skipped.stderr)
    assert "too big to read" not in (skipped.stdout + skipped.stderr)
    assert len(load_inbox(ProjectPaths(root).inbox).proposed()) == 1

    broken = tmp_path / "broken.md"
    broken.write_bytes(b"Decision: bytes were replaced -- still one line\n\xff\n")
    config.write_text(
        config.read_text(encoding="utf-8").replace("max_bytes = 1024", "max_bytes = 1048576"),
        encoding="utf-8",
    )
    survived = _import(invoke, root, "plain", broken)
    assert survived.exit_code == 0, survived.stdout + survived.stderr
    assert "bytes were replaced" in survived.stdout

    unknown = invoke(["--root", str(root), "import", "nope", str(notes)])
    assert unknown.exit_code == 2
    assert "unknown source" in (unknown.stdout + unknown.stderr)
