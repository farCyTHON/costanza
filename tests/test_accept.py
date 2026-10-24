from __future__ import annotations

import os
from pathlib import Path

import pytest

from costanza.inbox import load_inbox
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--name", "shopbot"])
    assert result.exit_code == 0, result.output


def test_accept_without_tty_exits_2(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "SQLite -- zero ops"])
    before_file = (tmp_path / "COSTANZA.md").read_bytes()
    before_inbox = (tmp_path / ".costanza" / "inbox.jsonl").read_bytes()
    before_ledger = (tmp_path / ".costanza" / "archive" / "ids").read_bytes()
    result = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert result.exit_code == 2
    assert "interactive" in result.stderr
    assert (tmp_path / "COSTANZA.md").read_bytes() == before_file
    assert (tmp_path / ".costanza" / "inbox.jsonl").read_bytes() == before_inbox
    assert (tmp_path / ".costanza" / "archive" / "ids").read_bytes() == before_ledger


def test_accept_gate_no_writes_nothing(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "SQLite -- zero ops"])
    monkeypatch.setattr("costanza.gate.confirm", lambda *a, **k: False)
    before = (tmp_path / "COSTANZA.md").read_bytes()
    result = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert result.exit_code == 0
    assert "nothing accepted" in result.stdout + result.stderr
    assert (tmp_path / "COSTANZA.md").read_bytes() == before


def test_accept_round_trip(invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(invoke, tmp_path)
    called: list[str] = []

    def confirm(message: str, *, preconfirmed: bool = False) -> bool:
        called.append(message)
        return True

    monkeypatch.setattr("costanza.gate.confirm", confirm)
    invoke(["--root", str(tmp_path), "decide", "SQLite, not Postgres -- zero ops", "--files", "src/costanza/format.py"])
    result = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert result.exit_code == 0, result.output
    assert "p1 → D1" in result.stdout
    assert called
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "D1 SQLite, not Postgres -- zero ops" in text
    assert "[files: src/costanza/format.py]" in text
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    item = inbox.by_id("p1")
    assert item is not None
    assert item.status == "accepted"
    assert item.entry == "D1"
    assert item.via == "accept"
    assert item.decided
    ledger = (tmp_path / ".costanza" / "archive" / "ids").read_text(encoding="utf-8")
    assert "D 1" in ledger
    again = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert again.exit_code == 0
    assert "already accepted as D1" in again.stdout + again.stderr


def test_hand_deleted_id_is_not_reused(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    monkeypatch.setattr("costanza.gate.confirm", lambda *a, **k: True)
    invoke(["--root", str(tmp_path), "decide", "first -- a"])
    accepted = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert accepted.exit_code == 0, accepted.output
    ledger = (tmp_path / ".costanza" / "archive" / "ids").read_text(encoding="utf-8")
    assert "D 1" in ledger
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    (tmp_path / "COSTANZA.md").write_text(text.replace("D1 first -- a\n", ""), encoding="utf-8")
    invoke(["--root", str(tmp_path), "decide", "second -- b"])
    again = invoke(["--root", str(tmp_path), "accept", "p2"])
    assert again.exit_code == 0, again.output
    after = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "D1 " not in after
    assert "D2 second -- b" in after
    assert "D 2" in (tmp_path / ".costanza" / "archive" / "ids").read_text(encoding="utf-8")


def test_accept_kinds(invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(invoke, tmp_path)
    monkeypatch.setattr("costanza.gate.confirm", lambda *a, **k: True)
    invoke(["--root", str(tmp_path), "reject", "SQLAlchemy -- too heavy"])
    invoke(["--root", str(tmp_path), "rule", "type hints required"])
    invoke(["--root", str(tmp_path), "gotcha", "webhook dupes -- dedupe"])
    invoke(["--root", str(tmp_path), "ask", "rate limit per user?"])
    invoke(["--root", str(tmp_path), "accept", "--all"])
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "X1 SQLAlchemy -- too heavy" in text
    assert "R1 type hints required" in text
    assert "G1 webhook dupes -- dedupe" in text
    assert "Q1 rate limit per user?" in text


def test_dismiss_does_not_touch_file(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "A -- b"])
    invoke(["--root", str(tmp_path), "decide", "C -- d"])
    before = (tmp_path / "COSTANZA.md").read_bytes()
    one = invoke(["--root", str(tmp_path), "dismiss", "p1"])
    two = invoke(["--root", str(tmp_path), "dismiss", "p2", "--reject"])
    assert one.exit_code == 0 and two.exit_code == 0
    assert (tmp_path / "COSTANZA.md").read_bytes() == before
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    assert inbox.by_id("p1") is not None and inbox.by_id("p1").status == "dismissed"
    assert inbox.by_id("p2") is not None and inbox.by_id("p2").status == "rejected"


def test_accept_dismissed_exits_1(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "A -- b"])
    invoke(["--root", str(tmp_path), "dismiss", "p1"])
    result = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert result.exit_code == 1
    assert "dismissed" in result.stderr


def test_review_warns_to_edit_before_accepting(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "n" * 158])
    monkeypatch.setattr("costanza.ui.is_tty", lambda: True)
    monkeypatch.setattr("costanza.ui.read_key", lambda: "q")
    result = invoke(["--root", str(tmp_path), "review"])
    assert result.exit_code == 0, result.output
    assert (
        "this will be 161 characters; limit 160, shorten it; press e before accepting"
        in result.stderr
    )


def test_review_needs_tty(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "review"])
    assert result.exit_code == 2
    assert "interactive" in result.stderr


def test_review_scripted_keys(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "alpha -- a"])
    invoke(["--root", str(tmp_path), "decide", "beta -- b"])
    invoke(["--root", str(tmp_path), "gotcha", "gamma -- g"])
    invoke(["--root", str(tmp_path), "ask", "delta?"])
    invoke(["--root", str(tmp_path), "rule", "epsilon"])
    keys = iter(["a", "d", "e", "s", "q"])
    lines = iter(["gamma edited", "g", ""])
    monkeypatch.setattr("costanza.ui.is_tty", lambda: True)
    monkeypatch.setattr("costanza.ui.read_key", lambda: next(keys))
    monkeypatch.setattr("costanza.ui.read_line", lambda label, default: next(lines, default))
    monkeypatch.setattr("costanza.ui.ask_yes_no", lambda _message: True)
    monkeypatch.setattr("costanza.gate.confirm", lambda *a, **k: True)
    result = invoke(["--root", str(tmp_path), "review"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "D1 alpha" in text
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    assert inbox.by_id("p1") is not None and inbox.by_id("p1").via == "review"
    assert inbox.by_id("p2") is not None and inbox.by_id("p2").status == "dismissed"
    assert inbox.by_id("p3") is not None and inbox.by_id("p3").text == "gamma edited"


def test_review_suggested_first(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "older -- a"])
    invoke(["--root", str(tmp_path), "decide", "newer -- b"])
    inbox_path = tmp_path / ".costanza" / "inbox.jsonl"
    text = inbox_path.read_text(encoding="utf-8")
    text = text.replace('"id":"p2"', '"id":"p2","suggested":"abc1234"', 1)
    # the replace might break JSON if key already exists - do a cleaner edit
    inbox = load_inbox(inbox_path)
    p2 = inbox.by_id("p2")
    assert p2 is not None
    p2.suggested = "abc1234"
    from costanza.inbox import dump_inbox

    inbox_path.write_text(dump_inbox(inbox), encoding="utf-8")
    seen: list[str] = []

    def show(item: object, index: int, total: int) -> None:
        from costanza.inbox import Proposal

        assert isinstance(item, Proposal)
        seen.append(item.id)

    keys = iter(["q"])
    monkeypatch.setattr("costanza.ui.is_tty", lambda: True)
    monkeypatch.setattr("costanza.ui.read_key", lambda: next(keys))
    monkeypatch.setattr("costanza.ui.render_review_card", show)
    invoke(["--root", str(tmp_path), "review"])
    assert seen[0] == "p2"


def test_now_updates_and_add_done(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    shown = invoke(["--root", str(tmp_path), "now"])
    assert shown.exit_code == 0
    assert "doing: none" in shown.stdout
    one = invoke(["--root", str(tmp_path), "now", "--doing", "Step 4 inbox"])
    assert one.exit_code == 0
    assert "doing: Step 4 inbox" in (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    invoke(["--root", str(tmp_path), "now", "--add-done", "init"])
    invoke(["--root", str(tmp_path), "now", "--add-done", "format engine"])
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "done: format engine, init" in text
    bad = invoke(["--root", str(tmp_path), "now", "--done", "x", "--add-done", "y"])
    assert bad.exit_code == 2


def test_resolve_decide_and_note(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    monkeypatch.setattr("costanza.gate.confirm", lambda *a, **k: True)
    invoke(["--root", str(tmp_path), "ask", "rate limit per user or IP?"])
    invoke(["--root", str(tmp_path), "accept", "p1"])
    before = (tmp_path / "COSTANZA.md").read_bytes()
    decided = invoke(["--root", str(tmp_path), "resolve", "Q1", "--decide", "per user -- simpler"])
    assert decided.exit_code == 0
    assert (tmp_path / "COSTANZA.md").read_bytes() == before
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    p2 = inbox.by_id("p2")
    assert p2 is not None and p2.resolves == "Q1"
    invoke(["--root", str(tmp_path), "accept", "p2"])
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "Q1 " not in text.split("## OPEN")[-1] or "Q1 rate" not in text
    archives = list((tmp_path / ".costanza" / "archive").glob("*.md"))
    assert archives
    invoke(["--root", str(tmp_path), "ask", "another question"])
    invoke(["--root", str(tmp_path), "accept", "p3"])
    noted = invoke(["--root", str(tmp_path), "resolve", "Q2", "--note", "later"])
    assert noted.exit_code == 0
    assert "Q2 another question" not in (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")


def test_resolve_d_is_usage(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "resolve", "D1", "--note", "no"])
    assert result.exit_code == 2


def test_resolve_decide_missing_id_matches_note(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    before_file = (tmp_path / "COSTANZA.md").read_bytes()
    inbox = tmp_path / ".costanza" / "inbox.jsonl"
    before_inbox = inbox.read_bytes() if inbox.exists() else None
    noted = invoke(["--root", str(tmp_path), "resolve", "Q1", "--note", "closed"])
    decided = invoke(
        ["--root", str(tmp_path), "resolve", "Q1", "--decide", "keep one file -- closed"]
    )
    assert noted.exit_code == 2
    assert decided.exit_code == 2
    assert decided.output == noted.output
    assert "Q1 is not a Q or G entry in COSTANZA.md" in decided.output
    assert "next: cz status" in decided.output
    assert "proposed" not in decided.output
    assert (tmp_path / "COSTANZA.md").read_bytes() == before_file
    after_inbox = inbox.read_bytes() if inbox.exists() else None
    assert after_inbox == before_inbox


def test_atomic_write_failure_leaves_original(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    original = (tmp_path / "COSTANZA.md").read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    result = invoke(["--root", str(tmp_path), "now", "--doing", "should fail"])
    assert result.exit_code == 1
    assert (tmp_path / "COSTANZA.md").read_bytes() == original


def test_merge_when_user_edits(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    monkeypatch.setattr("costanza.gate.confirm", lambda *a, **k: True)
    invoke(["--root", str(tmp_path), "decide", "first -- a"])

    from costanza import store as store_mod
    from costanza.format import Entry, render
    from costanza.format import parse as parse_cf1
    from costanza.store import add_entry

    real_mutate = store_mod.mutate_file

    def sneaky(paths: object, previous_text: str, mutator: object, change: str) -> object:
        # Simulate a hand edit after Costanza read the file.
        current = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
        doc = parse_cf1(current)
        extra = Entry(kind="D", number=9, text="hand edit", reason="user")
        (tmp_path / "COSTANZA.md").write_text(render(add_entry(doc, extra)), encoding="utf-8")
        return real_mutate(paths, previous_text, mutator, change)  # type: ignore[arg-type]

    monkeypatch.setattr("costanza.accept.mutate_file", sneaky)
    result = invoke(["--root", str(tmp_path), "accept", "p1"])
    assert result.exit_code == 0
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "D9 hand edit" in text
    assert "first -- a" in text
    assert "merged" in result.stdout + result.stderr


def test_authoritative_paths_call_gate() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "costanza" / "accept.py"
    text = source.read_text(encoding="utf-8")
    assert text.count("gate.confirm") >= 2


def test_backup_written(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "now", "--doing", "work"])
    bak = tmp_path / ".costanza" / "backup" / "COSTANZA.md.bak"
    assert bak.is_file()
    assert "doing: none" in bak.read_text(encoding="utf-8")


def _suggest(root: Path, pid: str) -> None:
    from costanza.inbox import load_inbox, save_inbox
    from costanza.paths import ProjectPaths

    inbox = load_inbox(root / ".costanza" / "inbox.jsonl")
    item = inbox.by_id(pid)
    assert item is not None
    item.suggested = "abc1234"
    save_inbox(ProjectPaths(root), inbox)


def test_accept_suggested_lists_each_proposal(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "keep this one"])
    invoke(["--root", str(tmp_path), "decide", "leave this one"])
    _suggest(tmp_path, "p1")
    called: list[str] = []

    def confirm(message: str, *, preconfirmed: bool = False) -> bool:
        called.append(message)
        return True

    monkeypatch.setattr("costanza.gate.confirm", confirm)
    result = invoke(["--root", str(tmp_path), "accept", "--suggested"])
    assert result.exit_code == 0, result.output
    assert called and "keep this one" in called[0] and "p1" in called[0]
    assert "leave this one" not in called[0]
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "keep this one" in text
    assert "leave this one" not in text


def test_accept_suggested_declined_writes_nothing(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "keep this one"])
    _suggest(tmp_path, "p1")
    before = (tmp_path / "COSTANZA.md").read_bytes()
    monkeypatch.setattr("costanza.gate.confirm", lambda *_a, **_k: False)
    result = invoke(["--root", str(tmp_path), "accept", "--suggested"])
    assert result.exit_code == 0, result.output
    assert "nothing accepted" in result.stdout
    assert (tmp_path / "COSTANZA.md").read_bytes() == before


def test_accept_suggested_with_none_does_not_ask(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "plain proposal"])
    called: list[str] = []
    monkeypatch.setattr(
        "costanza.gate.confirm",
        lambda message, **_k: called.append(message) or True,
    )
    result = invoke(["--root", str(tmp_path), "accept", "--suggested"])
    assert result.exit_code == 0, result.output
    assert called == []
    assert "nothing accepted" in result.stdout


def test_accept_suggested_rejects_ids(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "accept", "p1", "--suggested"])
    assert result.exit_code == 2
    assert "--suggested" in result.stderr
