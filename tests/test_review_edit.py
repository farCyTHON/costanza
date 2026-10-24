"""Review edit asks before writing, and Ctrl+C leaves the inbox alone."""

from __future__ import annotations

from pathlib import Path

import pytest

from costanza.accept import ReviewHooks, review_loop
from costanza.inbox import load_inbox
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--name", "shopbot", "--agents", "none"])
    assert result.exit_code == 0, result.output


def _hooks(
    keys: list[str],
    lines: list[str],
    answers: list[bool],
    shown: list[str],
) -> ReviewHooks:
    key_iter = iter(keys)
    line_iter = iter(lines)
    answer_iter = iter(answers)
    return ReviewHooks(
        is_tty=lambda: True,
        read_key=lambda: next(key_iter),
        read_line=lambda _label, default: next(line_iter, default),
        confirm=lambda _message: next(answer_iter),
        show=lambda *_args: None,
        ok=lambda _message: None,
        info=shown.append,
        warn=lambda _message: None,
        err=lambda _message: None,
    )


def test_declined_edit_is_not_written(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "original wording"])
    before = (tmp_path / ".costanza" / "inbox.jsonl").read_bytes()
    shown: list[str] = []
    review_loop(
        hooks=_hooks(["e", "q"], ["rewritten wording", "", ""], [False], shown),
        explicit=tmp_path,
    )
    assert any("rewritten wording" in line for line in shown)
    assert (tmp_path / ".costanza" / "inbox.jsonl").read_bytes() == before


def test_confirmed_edit_is_written(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "original wording"])
    review_loop(
        hooks=_hooks(["e", "q"], ["rewritten wording", "", ""], [True], []),
        explicit=tmp_path,
    )
    item = load_inbox(tmp_path / ".costanza" / "inbox.jsonl").by_id("p1")
    assert item is not None
    assert item.text == "rewritten wording"


def test_ctrl_c_during_edit_confirm_writes_nothing(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "decide", "original wording"])
    before = (tmp_path / ".costanza" / "inbox.jsonl").read_bytes()

    def stop(_message: str) -> bool:
        raise KeyboardInterrupt

    hooks = _hooks(["e"], ["rewritten wording", "", ""], [], [])
    hooks.confirm = stop
    with pytest.raises(KeyboardInterrupt):
        review_loop(hooks=hooks, explicit=tmp_path)
    assert (tmp_path / ".costanza" / "inbox.jsonl").read_bytes() == before


def test_ctrl_c_prints_cancelled(invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(invoke, tmp_path)

    def stop(**_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("costanza.accept.review_loop", stop)
    result = invoke(["--root", str(tmp_path), "review"])
    assert result.exit_code == 130
    assert "cancelled" in result.stderr
    assert "Traceback" not in result.output


def test_read_line_wraps_at_narrow_width(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from costanza.ui import configure, read_line

    monkeypatch.setenv("COLUMNS", "40")
    monkeypatch.setattr("sys.stdin.readline", lambda: "\n")
    configure(no_color=True)
    default = "one two three four five six seven eight nine ten"
    assert read_line("text", default) == default
    printed = capsys.readouterr().out
    assert printed.count("\n") >= 2
