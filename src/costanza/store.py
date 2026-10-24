"""Atomic COSTANZA.md writes with backup and merge-on-edit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from costanza.constants import KINDS
from costanza.exceptions import ParseError
from costanza.format import Document, Entry, Header, Now, high_water, parse, render
from costanza.io import copy_bytes, read_text, write_text
from costanza.lock import hold_lock
from costanza.paths import ProjectPaths


@dataclass
class WriteResult:
    text: str
    merged: bool
    change: str


def read_file(paths: ProjectPaths) -> tuple[str, Document]:
    if not paths.file.is_file():
        from costanza.exceptions import NotFoundError

        raise NotFoundError(f"no COSTANZA.md found in {paths.root}", "cz init")
    text = read_text(paths.file)
    document = parse(text)
    if not document.readable or not document.marker_ok or document.version != 1:
        raise ParseError(
            "COSTANZA.md line 1: missing or unsupported marker",
            "fix that line, then cz check",
        )
    return text, document


def archive_texts(paths: ProjectPaths) -> list[str]:
    texts: list[str] = []
    if not paths.archive_dir.is_dir():
        return texts
    for path in sorted(paths.archive_dir.iterdir()):
        if path.is_file():
            texts.append(read_text(path))
    return texts


def write_ledger(paths: ProjectPaths, document: Document) -> None:
    marks = high_water(document, *archive_texts(paths))
    lines = ["# costanza id ledger v1: highest ID ever issued per kind; do not edit"]
    for kind in KINDS:
        lines.append(f"{kind} {marks[kind]}")
    paths.archive_dir.mkdir(parents=True, exist_ok=True)
    write_text(paths.ledger, "\n".join(lines) + "\n")


def _backup(paths: ProjectPaths) -> None:
    if not paths.file.is_file():
        return
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    copy_bytes(paths.file, paths.file_write_bak)


def mutate_file(
    paths: ProjectPaths,
    previous_text: str,
    mutator: Callable[[Document], Document],
    change: str,
) -> WriteResult:
    """Apply ``mutator`` to the file currently on disk.

    If the user edited COSTANZA.md since ``previous_text`` was read, the
    mutator still runs on the latest parse so their edit is never overwritten.
    """
    with hold_lock(paths):
        current = read_text(paths.file) if paths.file.is_file() else ""
        merged = current != previous_text
        document = parse(current) if current else parse(previous_text)
        if not document.readable or not document.marker_ok:
            raise ParseError(
                "COSTANZA.md line 1: missing or unsupported marker",
                "fix that line, then cz check",
            )
        updated = mutator(document)
        _backup(paths)
        text = render(updated)
        write_text(paths.file, text)
        write_ledger(paths, updated)
        return WriteResult(text=text, merged=merged, change=change)


def add_entry(document: Document, entry: Entry) -> Document:
    buckets = {
        "D": list(document.decisions),
        "X": list(document.rejected),
        "R": list(document.rules),
        "G": list(document.gotchas),
        "Q": list(document.open),
    }
    buckets[entry.kind].append(entry)
    buckets[entry.kind].sort(key=lambda item: item.number)
    return replace(
        document,
        decisions=tuple(buckets["D"]),
        rejected=tuple(buckets["X"]),
        rules=tuple(buckets["R"]),
        gotchas=tuple(buckets["G"]),
        open=tuple(buckets["Q"]),
    )


def drop_entry(document: Document, entry_id: str) -> tuple[Document, Entry | None]:
    found: Entry | None = None
    buckets: dict[str, list[Entry]] = {
        "D": [],
        "X": [],
        "R": [],
        "G": [],
        "Q": [],
    }
    mapping = {
        "decisions": "D",
        "rejected": "X",
        "rules": "R",
        "gotchas": "G",
        "open": "Q",
    }
    for attr, kind in mapping.items():
        for item in getattr(document, attr):
            if item.id == entry_id:
                found = item
            else:
                buckets[kind].append(item)
    return (
        replace(
            document,
            decisions=tuple(buckets["D"]),
            rejected=tuple(buckets["X"]),
            rules=tuple(buckets["R"]),
            gotchas=tuple(buckets["G"]),
            open=tuple(buckets["Q"]),
        ),
        found,
    )


def replace_now(document: Document, now: Now) -> Document:
    return replace(document, now=now)


def append_archive(paths: ProjectPaths, heading: str, entry_line: str) -> Path:
    return append_archive_lines(paths, heading, [entry_line])


def append_archive_lines(paths: ProjectPaths, heading: str, entry_lines: list[str]) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m")
    path = paths.archive_dir / f"{today}.md"
    paths.archive_dir.mkdir(parents=True, exist_ok=True)
    block = "\n".join([heading, *entry_lines])
    if path.is_file():
        existing = read_text(path)
        if not existing.endswith("\n"):
            existing += "\n"
        body = existing + f"\n{block}\n"
    else:
        body = f"<!-- costanza archive v1 -->\n\n{block}\n"
    write_text(path, body)
    return path


def set_header_extra(header: Header, key: str, value: str) -> Header:
    extras = [(name, item) for name, item in header.extras if name != key]
    extras.append((key, value))
    return replace(header, extras=tuple(extras))
