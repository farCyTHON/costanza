from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from rich.console import Console

from costanza import ui
from costanza.cf1 import parse as parse_cf1
from costanza.check import CheckReport
from costanza.compact import CompactResult
from costanza.config import Config
from costanza.format import Finding, parse
from costanza.inbox import Proposal
from costanza.status import StatusView, build_view

FIXTURES = Path(__file__).parent / "fixtures"


@contextmanager
def recorded(width: int) -> Iterator[Console]:
    previous_cols = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(width)
    previous = (ui._out, ui._err)
    ui.configure(no_color=True, quiet=False, color_policy="never", ascii_policy="always")
    rec = Console(
        record=True,
        theme=ui.THEME,
        highlight=False,
        emoji=False,
        width=width,
        no_color=True,
        legacy_windows=False,
        force_terminal=True,
    )
    ui._out = rec
    ui._err = rec
    try:
        yield rec
    finally:
        ui._out, ui._err = previous
        if previous_cols is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous_cols
        ui.configure(no_color=True, quiet=False)


def _tiny_view(root: Path, tiny_text: str) -> StatusView:
    return build_view(root, tiny_text, parse_cf1(tiny_text), Config(), 14)


def _assert_no_mid_token(text: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in text.replace("\n", ""):
            continue
        assert any(token in line for line in text.splitlines()), f"{token!r} split:\n{text}"


def _assert_width(text: str, width: int) -> None:
    for line in text.splitlines():
        if len(line) <= width:
            continue
        assert " " not in line.strip(), f"line {len(line)} > {width}: {line!r}"


def _renderers(tmp_path: Path, tiny_text: str) -> dict[str, object]:
    view = _tiny_view(tmp_path, tiny_text)
    view.now["doing"] = (
        "payment webhook retries with backoff (app/services/pay.py, app/jobs/retry.py)"
    )
    report = CheckReport(
        root=tmp_path,
        findings=[
            Finding("W101", "warning", 0, "near budget: 93% of 1,800", hint="cz compact"),
            Finding(
                "W103",
                "warning",
                22,
                "line 22: [files: app/routes/admin.py] matches nothing",
                hint="fix the path",
            ),
        ],
        tokens=1666,
        budget=1800,
        document=parse(tiny_text),
    )
    proposal = Proposal(
        id="p7",
        kind="D",
        text="retry webhooks with exponential backoff, max 5 tries and keep going",
        why="provider retries for 24h anyway so we should match that window",
        files=["app/services/pay.py"],
        source="cli",
        ts="2026-10-12T14:02:00Z",
    )
    compact = CompactResult(
        moved=[],
        archive=None,
        tokens_before=181,
        tokens_after=181,
        target=1530,
        applied=False,
        still_over=[],
        nothing=True,
        budget=1800,
        compact_ratio=0.85,
    )
    return {
        "status": lambda: ui.render_status(view),
        "check": lambda: ui.render_check(report),
        "review": lambda: ui.render_review_card(proposal, 0, 14),
        "compact": lambda: ui.render_compact(compact),
    }


@pytest.mark.parametrize("width", [50, 80, 120])
@pytest.mark.parametrize("screen", ["status", "check", "review", "compact"])
def test_width_snapshots(tmp_path: Path, tiny_text: str, width: int, screen: str) -> None:
    render = _renderers(tmp_path, tiny_text)[screen]
    with recorded(width) as rec:
        assert callable(render)
        render()
        text = rec.export_text()
    snap = FIXTURES / "width" / f"{screen}-{width}.txt"
    snap.parent.mkdir(parents=True, exist_ok=True)
    if not snap.exists():
        snap.write_text(text, encoding="utf-8", newline="\n")
    expected = snap.read_text(encoding="utf-8")
    assert text == expected
    _assert_width(text, width)
    _assert_no_mid_token(text, ("proposed", "1,800", "COSTANZA.md"))
    if screen == "review" and width == 50:
        lines = [line for line in text.splitlines() if line.strip()]
        assert any(line.strip() == "1 of 14" for line in lines)
        assert all("1 of 14" not in line or line.strip() == "1 of 14" for line in lines)
    if screen == "compact":
        assert "target 1,530 = 85% of 1,800" in " ".join(text.split())
