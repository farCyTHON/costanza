"""Turn kept transcript lines into one-line candidates. Does not read a file."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from costanza.paste import CLOSE_RE, OPEN_RE, parse_item_line

LABEL_RE = re.compile(
    r"^(open question|decision|rejected|rule|gotcha)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_LABEL_WORD = {
    "decision": "decide",
    "rejected": "reject",
    "rule": "rule",
    "gotcha": "gotcha",
    "open question": "ask",
}


@dataclass
class Candidate:
    kind: str
    text: str
    why: str | None
    files: tuple[str, ...]
    line: int


@dataclass
class ScanResult:
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    truncated: bool = False


def scan_lines(lines: Iterator[tuple[int, str]], *, truncated: bool = False) -> ScanResult:
    """Scan visible lines. An unclosed costanza fence is dropped."""
    result = ScanResult(truncated=truncated)
    fence: list[tuple[int, str]] | None = None
    fence_mark = ""
    for number, line in lines:
        if fence is not None:
            close = CLOSE_RE.match(line.rstrip())
            if close is not None and close.group(1) == fence_mark:
                _flush_fence(fence, result)
                fence = None
                continue
            fence.append((number, line))
            continue
        opened = OPEN_RE.match(line.rstrip())
        if opened is not None:
            fence = []
            fence_mark = opened.group(1)
            continue
        _take_label(number, line, result)
    if fence is not None:
        result.truncated = True
    return result


def iter_text_file(path: Path) -> Iterator[tuple[int, str]]:
    """Stream a text file one line at a time. Never reads it into one string."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for number, raw in enumerate(handle, start=1):
            yield number, raw.rstrip("\r\n")


def _flush_fence(body: list[tuple[int, str]], result: ScanResult) -> None:
    for number, line in body:
        if _take_label(number, line, result):
            continue
        item, issue, ignored = parse_item_line(line, number)
        if ignored or (item is not None and item.now_key is not None):
            continue
        if item is not None and item.kind in {"D", "X", "R", "G", "Q"}:
            result.candidates.append(_from_item(item))
            continue
        if issue is not None:
            result.skipped.append(f"line {number}: {issue.message}")


def _take_label(number: int, line: str, result: ScanResult) -> bool:
    match = LABEL_RE.match(line.strip())
    if match is None:
        return False
    word = _LABEL_WORD[match.group(1).lower()]
    rewritten = f"{word}: {match.group(2)}"
    item, issue, ignored = parse_item_line(rewritten, number)
    if ignored or item is None or item.kind not in {"D", "X", "R", "G", "Q"}:
        message = "empty text" if issue is None else issue.message
        result.skipped.append(f"line {number}: {message}")
        return True
    result.candidates.append(_from_item(item))
    return True


def _from_item(item: object) -> Candidate:
    from costanza.paste import PasteItem

    assert isinstance(item, PasteItem)
    return Candidate(
        kind=item.kind,
        text=item.text,
        why=item.why,
        files=tuple(item.files),
        line=item.line,
    )
