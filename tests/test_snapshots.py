from __future__ import annotations

import io
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from rich.console import Console

from costanza import ui
from costanza.constants import skeleton
from costanza.inbox import Proposal
from tests.helpers import InvokeFn, InvokeResult


def _write(root: Path, text: str) -> None:
    (root / "COSTANZA.md").write_text(text, encoding="utf-8", newline="\n")


def test_snapshot_init_unicode(invoke: InvokeFn, tmp_path: Path) -> None:
    result: InvokeResult = invoke(["--root", str(tmp_path), "init"], env={"COSTANZA_ASCII": "0"})
    assert result.exit_code == 0
    assert "costanza initialized in" in result.stdout
    assert "COSTANZA.md" in result.stdout
    assert ".costanza/config.toml" in result.stdout
    assert ".costanza/archive/ids" in result.stdout
    assert "next: edit the header in COSTANZA.md, then cz status" in result.stdout


def test_snapshot_init_exists(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])
    result: InvokeResult = invoke(["--root", str(tmp_path), "init"], env={"COSTANZA_ASCII": "0"})
    assert result.exit_code == 1
    assert "already exists" in result.stderr
    assert "next:" in result.stderr


def test_snapshot_status_tiny(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text)
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"], env={"COSTANZA_ASCII": "0"})
    out = result.stdout
    assert "costanza" in out
    assert "shopbot, Telegram order bot" in out
    assert "tokens" in out
    assert "NOW" in out
    assert "blocked" in out


def test_snapshot_status_near(invoke: InvokeFn, tmp_path: Path, near_text: str) -> None:
    _write(tmp_path, near_text)
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"], env={"COSTANZA_ASCII": "0"})
    assert result.exit_code == 0
    assert "1,666" in result.stdout


def test_snapshot_status_skeleton(invoke: InvokeFn, tmp_path: Path) -> None:
    _write(tmp_path, skeleton("demo"))
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"], env={"COSTANZA_ASCII": "0"})
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "doing" in result.stdout


def test_snapshot_check_tiny_clean(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text)
    result = invoke(["--root", str(tmp_path), "check"], env={"COSTANZA_ASCII": "1"})
    assert result.exit_code == 0
    assert "COSTANZA.md is valid" in result.stdout
    assert "238" in result.stdout
    assert "0 warnings" in result.stdout


def test_snapshot_check_findings(invoke: InvokeFn, tmp_path: Path, near_text: str) -> None:
    _write(tmp_path, near_text)
    result = invoke(["--root", str(tmp_path), "check"], env={"COSTANZA_ASCII": "1"})
    assert result.exit_code == 0
    assert "W101" in result.stderr
    assert "W103" in result.stderr
    assert "check" in result.stdout
    assert "1,666" in result.stdout or "1666" in result.stdout


def test_snapshot_error_ascii(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])
    result: InvokeResult = invoke(["--root", str(tmp_path), "init"], env={"COSTANZA_ASCII": "1"})
    assert result.exit_code == 1
    assert all(ord(ch) < 128 for ch in result.stderr)
    assert "error" in result.stderr


@pytest.fixture
def record_ui() -> Iterator[Console]:
    previous = (ui._out, ui._err)
    ui.configure(no_color=True, quiet=False, color_policy="never", ascii_policy="always")
    rec = Console(
        record=True,
        theme=ui.THEME,
        highlight=False,
        emoji=False,
        width=80,
        no_color=True,
        legacy_windows=False,
        force_terminal=True,
    )
    ui._out = rec
    ui._err = rec
    yield rec
    ui._out, ui._err = previous
    ui.configure(no_color=True, quiet=False)


def test_snapshot_review_hint_bar(record_ui: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("q\n"))
    assert ui.read_key() == "q"
    text = record_ui.export_text()
    assert text == "[a]ccept  [r]eject  [d]ismiss  [e]dit  [s]kip  [q]uit  > \n"
    assert "ccept  eject" not in text


def test_snapshot_review_card_literal_markup(record_ui: Console) -> None:
    item = Proposal(
        id="p1",
        kind="D",
        text="keep [bold] and [/] in the log line",
        why="also [red] in why",
        files=["src/[id].py"],
        source="cli",
        ts="2026-10-13T00:00:00Z",
    )
    ui.render_review_card(item, 0, 1)
    text = record_ui.export_text()
    assert "keep [bold] and [/] in the log line" in text
    assert "also [red] in why" in text
    assert "src/[id].py" in text
    ui.error_panel("failed: [bold]secret[/]", "retry with [--force]")
    panel = record_ui.export_text()
    assert "failed: [bold]secret[/]" in panel
    assert "retry with [--force]" in panel
