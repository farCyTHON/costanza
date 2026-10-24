from __future__ import annotations

from pathlib import Path

from costanza.text import clip_words
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])


def _done(root: Path) -> str:
    for line in (root / "COSTANZA.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("done:"):
            return line[len("done:") :].strip()
    raise AssertionError("no done line")


def _next(root: Path) -> str:
    for line in (root / "COSTANZA.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("next:"):
            return line[len("next:") :].strip()
    raise AssertionError("no next line")


def test_clip_words_boundary_and_hard_cut() -> None:
    assert clip_words("one two three", 8) == "one two"
    assert clip_words("supercalifragilistic", 8) == "supercal"
    assert clip_words("short", 80) == "short"


def test_add_done_keeps_three_newest(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(["--root", str(tmp_path), "now", "--add-done", "one"])
    invoke(["--root", str(tmp_path), "now", "--add-done", "two"])
    invoke(["--root", str(tmp_path), "now", "--add-done", "three"])
    invoke(["--root", str(tmp_path), "now", "--add-done", "four"])
    assert _done(tmp_path) == "four, three, two"


def test_add_done_clips_item_to_sixty(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    long_item = "word " * 20  # well over 60
    result = invoke(["--root", str(tmp_path), "now", "--add-done", long_item])
    assert result.exit_code == 0, result.output
    item = _done(tmp_path)
    assert "," not in item
    assert len(item) <= 60


def test_now_value_over_160_truncates_and_warns(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    blob = "alpha " * 40  # 240 characters
    assert len(blob) > 160
    result = invoke(["--root", str(tmp_path), "now", "--doing", blob])
    assert result.exit_code == 0, result.output
    assert "truncated" in result.stderr
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    doing = next(line for line in text.splitlines() if line.startswith("doing:"))
    assert len(doing) <= 160
    assert "alpha" in doing


def test_done_and_next_keep_three_items(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    invoke(
        [
            "--root",
            str(tmp_path),
            "now",
            "--done",
            "newest, mid, old, dropped",
            "--next",
            "first, second, third, fourth",
        ]
    )
    assert _done(tmp_path) == "newest, mid, old"
    assert _next(tmp_path) == "first, second, third"


def test_now_done_and_add_done_conflict(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    bad = invoke(["--root", str(tmp_path), "now", "--done", "x", "--add-done", "y"])
    assert bad.exit_code == 2
