"""Lenient read-only CF1 reader (Step 2). Never raises on content findings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from costanza.constants import HEADER_KEYS, KINDS, KNOWN_SECTIONS, NOW_KEYS

MARKER_RE = re.compile(r"^<!-- costanza v(\d+)(?: \|.*)? -->$")
HEADER_SPLIT_RE = re.compile(r"\s\|\s(?=(stack|run|test|layout|synced):\s)")
PROJECT_RE = re.compile(r"^# PROJECT:\s*(.*)$")
ENTRY_HEAD_RE = re.compile(r"^([DXRGQ])([1-9][0-9]*)(?:\s+|$)")
PAIR_RE = re.compile(r"^([a-z][a-z0-9_-]*):\s*(.*)$")


@dataclass(frozen=True)
class Problem:
    line: int
    code: str
    message: str


@dataclass
class Document:
    """Whatever the lenient reader could recover."""

    readable: bool
    project: str = ""
    header: dict[str, str] = field(default_factory=dict)
    now: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    text: str = ""

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = {kind: 0 for kind in KINDS}
        if not self.now:
            self.now = {key: "none" for key in NOW_KEYS}
        for key in HEADER_KEYS:
            self.header.setdefault(key, "?" if key != "synced" else "never")


def _add(problems: list[Problem], line: int, code: str, message: str) -> None:
    problems.append(Problem(line=line, code=code, message=message))


def parse(text: str) -> Document:
    """Parse CF1 leniently. E001 is the only case that sets ``readable=False``."""
    problems: list[Problem] = []
    lines = text.splitlines()
    if not lines or not (match := MARKER_RE.match(lines[0].rstrip())):
        _add(problems, 1, "E001", "missing or unsupported marker")
        return Document(readable=False, problems=problems, text=text)
    if match.group(1) != "1":
        _add(problems, 1, "E001", f"unsupported version {match.group(1)}")
        return Document(readable=False, problems=problems, text=text)

    project = ""
    if len(lines) < 2 or not (proj := PROJECT_RE.match(lines[1].rstrip())):
        _add(problems, 2 if len(lines) >= 2 else 1, "E002", "missing # PROJECT: line")
    else:
        project = proj.group(1).strip()
        if not project:
            _add(problems, 2, "E002", "empty # PROJECT: line")

    header: dict[str, str] = {}
    index = 2
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if stripped == "":
            index += 1
            break
        if stripped.startswith("## "):
            break
        parts = _header_parts(stripped)
        if not parts:
            _add(problems, index + 1, "E003", "line not understood (header)")
            index += 1
            continue
        for key, value in parts:
            if key in HEADER_KEYS:
                if key in header:
                    _add(problems, index + 1, "E012", f"duplicate header key {key}")
                else:
                    header[key] = value
            elif PAIR_RE.match(f"{key}: {value}"):
                _add(problems, index + 1, "W105", f"unknown header key {key}")
            else:
                _add(problems, index + 1, "E003", "line not understood (header)")
        index += 1

    now: dict[str, str] = {}
    counts = {kind: 0 for kind in KINDS}
    current_kind: str | None = None
    seen_sections: set[str] = set()

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "":
            index += 1
            continue
        if stripped.startswith("## "):
            heading = stripped
            if heading == "## NOW":
                current_kind = "NOW"
                index += 1
                continue
            if heading in KNOWN_SECTIONS:
                if heading in seen_sections:
                    _add(problems, index + 1, "E014", f"duplicate section {heading}")
                seen_sections.add(heading)
                current_kind = KNOWN_SECTIONS[heading]
                index += 1
                continue
            current_kind = None
            index += 1
            continue
        if current_kind == "NOW":
            pair = PAIR_RE.match(stripped)
            if pair and pair.group(1) in NOW_KEYS:
                key = pair.group(1)
                if key in now:
                    _add(problems, index + 1, "E012", f"duplicate NOW key {key}")
                else:
                    now[key] = pair.group(2).strip() or "none"
            else:
                _add(problems, index + 1, "E003", "line not understood (NOW)")
            index += 1
            continue
        if current_kind in KINDS:
            head = ENTRY_HEAD_RE.match(stripped)
            if head is None:
                _add(problems, index + 1, "E003", "line not understood (section)")
            elif head.group(1) != current_kind:
                _add(problems, index + 1, "E004", "entry in the wrong section")
            else:
                counts[current_kind] += 1
            index += 1
            continue
        # Unknown section body: keep, do not validate (except later check).
        index += 1

    return Document(
        readable=True,
        project=project,
        header=header,
        now=now,
        counts=counts,
        problems=problems,
        text=text,
    )


def _header_parts(line: str) -> list[tuple[str, str]]:
    """Split a header line on `` | `` only before a known key."""
    parts: list[tuple[str, str]] = []
    rest = line
    while True:
        match = HEADER_SPLIT_RE.search(rest)
        if match is None:
            pair = PAIR_RE.match(rest)
            if pair:
                parts.append((pair.group(1), pair.group(2).strip()))
            elif rest.strip():
                return []
            break
        pair = PAIR_RE.match(rest[: match.start()])
        if pair:
            parts.append((pair.group(1), pair.group(2).strip()))
        else:
            return []
        rest = rest[match.end() :]
    return parts
