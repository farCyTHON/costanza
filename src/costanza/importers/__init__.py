"""Recover low-confidence inbox proposals from a saved session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from costanza.config import load_config
from costanza.exceptions import CostanzaError, NotFoundError, UsageError
from costanza.importers.aider import read_aider
from costanza.importers.claude import read_claude
from costanza.importers.plain import read_plain
from costanza.importers.scan import Candidate
from costanza.paths import ProjectPaths, discover_root
from costanza.propose import propose
from costanza.scrub import redact

SOURCES = ("plain", "aider", "claude-code")


@dataclass
class ImportReport:
    source: str
    path: Path
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    truncated: bool = False
    wrote: bool = False
    proposed: int = 0
    duplicate: int = 0
    redacted: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def import_transcript(
    source: str,
    path: Path,
    *,
    yes: bool = False,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> ImportReport:
    """Preview candidates, or write them when ``yes`` is set. Never accepts."""
    key = source.strip().lower()
    if key not in SOURCES:
        raise UsageError(
            f"unknown source {source!r}",
            "use plain, aider or claude-code",
        )
    if key == "claude-code":
        read_claude(path)
    if not path.is_file():
        raise NotFoundError(
            f"no such file: {path}",
            "pass the session file to import",
        )
    root = discover_root(cwd, explicit, allow_cwd=False)
    config = load_config(ProjectPaths(root).config)
    size = path.stat().st_size
    if size > config.import_max_bytes:
        raise CostanzaError(
            f"skipped {path.name}: {size} bytes is over import.max_bytes ({config.import_max_bytes})",
            "raise import.max_bytes or pass a smaller file",
        )
    scanned = read_plain(path) if key == "plain" else read_aider(path)
    allow = list(config.secret_allow)
    cleaned, names = _scrub(scanned.candidates, allow)
    report = ImportReport(
        source=key,
        path=path,
        candidates=cleaned,
        skipped=list(scanned.skipped),
        truncated=scanned.truncated,
        redacted=tuple(dict.fromkeys(names)),
    )
    if not yes:
        return report
    warnings: list[str] = []
    for item in cleaned:
        try:
            result = propose(
                item.kind,
                item.text,
                why=item.why,
                files=", ".join(item.files) if item.files else None,
                source="import",
                agent=key,
                extra={"confidence": "low"},
                cwd=cwd,
                explicit=explicit,
            )
        except UsageError as exc:
            report.skipped.append(f"line {item.line}: {exc.message}")
            continue
        if result.result == "proposed":
            report.proposed += 1
        elif result.result == "duplicate":
            report.duplicate += 1
        else:
            report.skipped.append(f"line {item.line}: {result.result}")
        warnings.extend(result.warnings)
        if result.redacted:
            names.extend(result.redacted)
    report.wrote = True
    report.redacted = tuple(dict.fromkeys(names))
    report.warnings = tuple(dict.fromkeys(warnings))
    return report


def _scrub(
    candidates: list[Candidate], allow: list[str]
) -> tuple[list[Candidate], list[str]]:
    cleaned: list[Candidate] = []
    names: list[str] = []
    for item in candidates:
        text = redact(item.text, allow)
        why_text = None
        why_names: tuple[str, ...] = ()
        if item.why is not None:
            why = redact(item.why, allow)
            why_text = why.text
            why_names = why.names
        names.extend(text.names)
        names.extend(why_names)
        cleaned.append(
            Candidate(
                kind=item.kind,
                text=text.text,
                why=why_text,
                files=item.files,
                line=item.line,
            )
        )
    return cleaned, names
