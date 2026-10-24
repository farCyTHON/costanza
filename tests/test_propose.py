from __future__ import annotations

from pathlib import Path

from costanza.inbox import load_inbox
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--name", "shopbot"])
    assert result.exit_code == 0, result.output


def test_decide_inline_why_leaves_file(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    before = (tmp_path / "COSTANZA.md").read_bytes()
    result = invoke(["--root", str(tmp_path), "decide", "SQLite, not Postgres -- zero ops"])
    assert result.exit_code == 0, result.output
    assert "p1 proposed" in result.stdout
    assert "D" in result.stdout
    assert (tmp_path / "COSTANZA.md").read_bytes() == before
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    item = inbox.proposals()[0]
    assert item.id == "p1"
    assert item.kind == "D"
    assert item.text == "SQLite, not Postgres"
    assert item.why == "zero ops"
    assert item.status == "proposed"


def test_inline_and_why_flag_is_usage(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "decide", "A -- b", "--why", "c"])
    assert result.exit_code == 2


def test_reject_needs_reason(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "reject", "SQLAlchemy"])
    assert result.exit_code == 2
    assert "reason" in result.stderr


def test_dedupe_normalized_hash(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    first = invoke(["--root", str(tmp_path), "decide", "use SQLite"])
    assert first.exit_code == 0
    second = invoke(["--root", str(tmp_path), "decide", "Use  sqlite."])
    assert second.exit_code == 0
    assert "duplicate of p1" in second.stdout + second.stderr
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    assert len(inbox.proposals()) == 1


def test_rejected_blocks_unless_force(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "Use SQLite"])
    invoke(["--root", str(tmp_path), "dismiss", "p1", "--reject"])
    blocked = invoke(["--root", str(tmp_path), "decide", "use SQLite"])
    assert blocked.exit_code == 0
    assert "previously rejected" in blocked.stdout + blocked.stderr
    forced = invoke(["--root", str(tmp_path), "decide", "use SQLite", "--force"])
    assert forced.exit_code == 0
    assert "p2 proposed" in forced.stdout


def test_dismissed_can_repropose(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "Use SQLite"])
    invoke(["--root", str(tmp_path), "dismiss", "p1"])
    again = invoke(["--root", str(tmp_path), "decide", "use SQLite"])
    assert again.exit_code == 0
    assert "p2 proposed" in again.stdout


def test_near_warning_for_similar_x(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "reject", "SQLAlchemy ORM -- too heavy"])
    result = invoke(["--root", str(tmp_path), "decide", "SQLAlchemy ORM layer -- maybe later"])
    assert result.exit_code == 0
    assert "close to p1" in result.stderr
    assert "rejected" in result.stderr


def test_decide_double_dash_text(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "decide", "--", "--no-color"])
    assert result.exit_code == 0, result.output
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    assert inbox.proposals()[0].text == "--no-color"


def test_bad_paths_and_forbidden(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    for path in ("../x", "/etc/passwd", "C:/x", "a\\b"):
        result = invoke(["--root", str(tmp_path), "decide", "ok", "--files", path])
        assert result.exit_code == 2, path
    for text in ("has \u202e bidi", "zero\u200bwidth", "esc\x1bape", "oops --> there"):
        result = invoke(["--root", str(tmp_path), "decide", text])
        assert result.exit_code == 2, repr(text)


def test_github_token_never_stored(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    token = "ghp_" + ("c" * 36)
    result = invoke(["--root", str(tmp_path), "decide", f"use {token} in ci -- no"])
    assert result.exit_code == 0
    assert "github_token" in result.stderr
    blob = (tmp_path / ".costanza" / "inbox.jsonl").read_text(encoding="utf-8")
    assert token not in blob
    assert "[REDACTED:github_token]" in blob


def test_ids_keep_increasing(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "one -- a"])
    invoke(["--root", str(tmp_path), "decide", "two -- b"])
    invoke(["--root", str(tmp_path), "dismiss", "p1"])
    invoke(["--root", str(tmp_path), "decide", "three -- c"])
    ids = [item.id for item in load_inbox(tmp_path / ".costanza" / "inbox.jsonl").proposals()]
    assert ids == ["p1", "p2", "p3"]


def test_invalid_json_kept(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    inbox = tmp_path / ".costanza" / "inbox.jsonl"
    inbox.write_text("not-json\n", encoding="utf-8")
    invoke(["--root", str(tmp_path), "decide", "ok -- why"])
    text = inbox.read_text(encoding="utf-8")
    assert text.startswith("not-json\n")
    assert "p1" in text


def test_max_open(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    config = tmp_path / ".costanza" / "config.toml"
    text = config.read_text(encoding="utf-8").replace("max_open = 100", "max_open = 1")
    config.write_text(text, encoding="utf-8")
    invoke(["--root", str(tmp_path), "decide", "one -- a"])
    result = invoke(["--root", str(tmp_path), "decide", "two -- b"])
    assert result.exit_code == 1
    assert "cz review" in result.stderr


def test_long_entry_warns_and_still_proposes(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    short = invoke(["--root", str(tmp_path), "decide", "keep the line short"])
    assert short.exit_code == 0
    assert "limit 160" not in short.stdout + short.stderr
    blob = "n" * 158
    warned = invoke(["--root", str(tmp_path), "propose", "D", blob])
    assert warned.exit_code == 0, warned.output
    assert "p2 proposed" in warned.stdout
    assert "this will be 161 characters; limit 160, shorten it" in warned.stderr
    for command in (
        ["decide", "d" * 158],
        ["rule", "r" * 158],
        ["gotcha", "g" * 158],
        ["ask", "q" * 158],
    ):
        result = invoke(["--root", str(tmp_path), *command])
        assert result.exit_code == 0, result.output
        assert "this will be 161 characters; limit 160, shorten it" in result.stderr
    rejected = invoke(["--root", str(tmp_path), "reject", "n" * 151, "--why", "why"])
    assert rejected.exit_code == 0, rejected.output
    assert "this will be 161 characters; limit 160, shorten it" in rejected.stderr
    fitting = invoke(["--root", str(tmp_path), "decide", "n" * 157])
    assert fitting.exit_code == 0
    assert "limit 160" not in fitting.stdout + fitting.stderr


def test_list_filters(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "one -- a"])
    invoke(["--root", str(tmp_path), "decide", "two -- b"])
    invoke(["--root", str(tmp_path), "dismiss", "p1"])
    listed = invoke(["--root", str(tmp_path), "list"])
    assert "p2" in listed.stdout
    assert "p1" not in listed.stdout
    all_json = invoke(["--root", str(tmp_path), "list", "--status", "all", "--json"])
    assert all_json.exit_code == 0
    assert "p1" in all_json.stdout
    assert "p2" in all_json.stdout
