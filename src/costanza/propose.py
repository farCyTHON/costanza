"""Propose pipeline: normalise, validate, redact, dedupe, append."""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from costanza.config import Config, load_config
from costanza.constants import KINDS
from costanza.exceptions import CostanzaError, UsageError
from costanza.format import Entry, length_warning, next_id, parse, render_entry
from costanza.inbox import Inbox, Proposal, append_proposal, load_inbox
from costanza.io import read_text
from costanza.paths import ProjectPaths, discover_root
from costanza.scrub import redact
from costanza.store import archive_texts
from costanza.text import content_hash, hash_norm, parse_files, require_clean, split_inline

KIND_ALIASES = {
    "d": "D",
    "decision": "D",
    "decisions": "D",
    "x": "X",
    "rejected": "X",
    "reject": "X",
    "r": "R",
    "rule": "R",
    "rules": "R",
    "g": "G",
    "gotcha": "G",
    "gotchas": "G",
    "q": "Q",
    "question": "Q",
    "ask": "Q",
    "open": "Q",
}
NEAR_RATIO = 0.72


@dataclass
class NearHit:
    ref: str
    ratio: float
    kind: str


@dataclass
class ProposeResult:
    result: str
    proposal: Proposal | None = None
    ref: str | None = None
    redacted: tuple[str, ...] = ()
    near: list[NearHit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "result": self.result,
            "id": None if self.proposal is None else self.proposal.id,
            "ref": self.ref,
            "redacted": list(self.redacted),
        }


def parse_kind(value: str) -> str:
    key = value.strip().lower()
    if key in KIND_ALIASES:
        return KIND_ALIASES[key]
    if value.strip().upper() in KINDS:
        return value.strip().upper()
    raise UsageError(
        f"unknown kind {value!r}; use D, X, R, G, Q or decision/rejected/rule/gotcha/question",
        "cz propose D \"text\"",
    )


def _agent(explicit: str | None) -> str | None:
    name = explicit if explicit is not None else os.environ.get("COSTANZA_AGENT")
    if name is None:
        return None
    name = name.strip()
    if len(name) > 64:
        raise UsageError("agent name is longer than 64 characters", "shorten --agent")
    return name or None


def _near_hits(kind: str, text: str, inbox: Inbox, file_entries: list[tuple[str, str, str]]) -> list[NearHit]:
    needle = hash_norm(text)
    hits: list[NearHit] = []
    for item in inbox.proposals():
        if item.purged or not item.text:
            continue
        ratio = difflib.SequenceMatcher(None, needle, hash_norm(item.text)).ratio()
        if ratio >= NEAR_RATIO and content_hash(item.kind, item.text) != content_hash(kind, text):
            hits.append(NearHit(ref=item.id, ratio=ratio, kind=item.kind))
    for entry_id, entry_kind, entry_text in file_entries:
        ratio = difflib.SequenceMatcher(None, needle, hash_norm(entry_text)).ratio()
        if ratio >= NEAR_RATIO:
            hits.append(NearHit(ref=entry_id, ratio=ratio, kind=entry_kind))
    hits.sort(key=lambda item: item.ratio, reverse=True)
    return hits[:3]


def propose(
    kind: str,
    text: str,
    *,
    why: str | None = None,
    files: str | None = None,
    source: str = "cli",
    agent: str | None = None,
    force: bool = False,
    resolves: str | None = None,
    extra: dict[str, Any] | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> ProposeResult:
    kind = parse_kind(kind)
    if source not in {"cli", "paste", "mcp", "import"}:
        raise UsageError("source must be cli, paste, mcp or import", "omit --source")
    raw_text, raw_why = split_inline(text, why)
    clean_text = require_clean(raw_text, "text")
    clean_why = require_clean(raw_why, "why") if raw_why is not None else None
    if kind == "X" and not clean_why:
        raise UsageError("rejected ideas need a reason", "cz reject \"idea -- why\" or pass --why")
    file_list = parse_files(files)
    agent_name = _agent(agent)

    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    allow = _secret_allow(config)

    red_text = redact(clean_text, allow)
    red_why = redact(clean_why, allow) if clean_why is not None else None
    names = list(red_text.names)
    if red_why is not None:
        names.extend(red_why.names)
    for path in file_list:
        names.extend(redact(path, allow).names)
    clean_text = red_text.text
    if red_why is not None:
        clean_why = red_why.text

    inbox = load_inbox(paths.inbox)
    archive = load_inbox(paths.inbox_archive)
    digest = content_hash(kind, clean_text)
    file_entries = _file_entries(paths)

    if not force:
        for item in inbox.proposals() + archive.proposals():
            if item.hash != digest:
                continue
            if item.status == "proposed":
                return ProposeResult(result="duplicate", ref=item.id, redacted=tuple(names))
            if item.status == "rejected":
                return ProposeResult(result="previously_rejected", ref=item.id, redacted=tuple(names))
        for entry_id, entry_kind, entry_text in file_entries:
            if entry_kind == kind and hash_norm(entry_text) == hash_norm(clean_text):
                return ProposeResult(result="already_present", ref=entry_id, redacted=tuple(names))
        for archived in archive_texts(paths):
            for raw in archived.splitlines():
                from costanza.format import ENTRY_LINE_RE, parse_entry_line

                if ENTRY_LINE_RE.match(raw.strip()):
                    parsed = parse_entry_line(raw.strip())
                    if (
                        parsed is not None
                        and parsed.kind == kind
                        and hash_norm(parsed.text) == hash_norm(clean_text)
                    ):
                        return ProposeResult(
                            result="already_archived",
                            ref=parsed.id,
                            redacted=tuple(names),
                        )

    if len(inbox.proposed()) >= config.max_open:
        raise CostanzaError(
            f"inbox has {config.max_open} open proposals",
            "cz review",
        )

    near = _near_hits(kind, clean_text, inbox, file_entries)
    preview = preview_entry_line(paths, kind, clean_text, clean_why, file_list)
    too_long = length_warning(preview)
    proposal = Proposal(
        id="",
        kind=kind,
        text=clean_text,
        why=clean_why,
        files=file_list,
        source=source,
        agent=agent_name,
        hash=digest,
        resolves=resolves,
        extra={} if extra is None else dict(extra),
    )
    stored = append_proposal(paths, proposal)
    warnings = [item.warning for item in inbox.lines if item.warning]
    if too_long:
        warnings.append(too_long)
    return ProposeResult(
        result="proposed",
        proposal=stored,
        redacted=tuple(dict.fromkeys(names)),
        near=near,
        warnings=warnings,
    )


def preview_entry_line(
    paths: ProjectPaths,
    kind: str,
    text: str,
    why: str | None,
    files: list[str],
    sha: str | None = None,
) -> str:
    """The entry line accept would write, using the next id for ``kind``."""
    if paths.file.is_file():
        document = parse(read_text(paths.file))
        entry_id = next_id(kind, document, *archive_texts(paths))
        number = int(entry_id[1:])
    else:
        number = 1
    return render_entry(
        Entry(kind=kind, number=number, text=text, reason=why, sha=sha, files=tuple(files))
    )


def _file_entries(paths: ProjectPaths) -> list[tuple[str, str, str]]:
    if not paths.file.is_file():
        return []
    document = parse(read_text(paths.file))
    return [(item.id, item.kind, item.text) for item in document.all_entries()]


def _secret_allow(config: Config) -> list[str]:
    return list(config.secret_allow)
