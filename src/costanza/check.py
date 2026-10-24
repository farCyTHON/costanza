"""COSTANZA.md health: format, budget, secrets, files, inbox, git."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from costanza.config import Config, load_config
from costanza.exceptions import NotFoundError
from costanza.format import (
    DRIVE_RE,
    SHA_RE,
    Document,
    Finding,
    ids_in_text,
    parse,
    render,
    validate,
)
from costanza.git import commits_behind, has_commits, probe
from costanza.inbox import load_inbox
from costanza.io import read_text
from costanza.paths import ProjectPaths, discover_root
from costanza.propose import NEAR_RATIO
from costanza.scrub import find_hits
from costanza.store import mutate_file
from costanza.text import hash_norm
from costanza.tokens import active_count, bind

E009 = "E009"
E010 = "E010"
W101 = "W101"
W103 = "W103"
W106 = "W106"
W107 = "W107"
W108 = "W108"
W109 = "W109"
W110 = "W110"


@dataclass
class CheckReport:
    root: Path
    findings: list[Finding]
    tokens: int
    budget: int
    document: Document
    fixed: bool = False

    @property
    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "warning"]

    def to_json(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "budget": self.budget,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "findings": [
                {
                    "code": item.code,
                    "severity": item.severity,
                    "file": item.path,
                    "line": item.line,
                    "message": item.message,
                    "hint": item.hint,
                }
                for item in self.findings
            ],
        }


def _finding(
    code: str,
    severity: str,
    line: int,
    message: str,
    *,
    path: str = "COSTANZA.md",
    hint: str = "",
) -> Finding:
    text = f"line {line}: {message}" if line else message
    return Finding(code=code, severity=severity, line=line, message=text, path=path, hint=hint)


def _budget_findings(tokens: int, config: Config) -> list[Finding]:
    warn_at = math.floor(config.budget_tokens * config.warn_at)
    if tokens > config.budget_tokens:
        return [
            _finding(
                E009,
                "error",
                0,
                f"over budget ({tokens:,} / {config.budget_tokens:,})",
                hint="cz compact",
            )
        ]
    if tokens >= warn_at:
        percent = 0 if config.budget_tokens <= 0 else round(100 * tokens / config.budget_tokens)
        return [
            _finding(
                W101,
                "warning",
                0,
                f"near budget: {percent}% of {config.budget_tokens:,}",
                hint="cz compact",
            )
        ]
    return []


def _secret_findings(text: str, path: str, allow: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for hit in find_hits(text, allow):
        out.append(
            _finding(
                E010,
                "error",
                hit.line,
                f"secret detected ({hit.name}): {hit.masked}",
                path=path,
                hint="remove it, rotate the credential, then cz check",
            )
        )
    return out


def _normalize_rel(rel: str) -> str:
    return rel.replace("\\", "/")


def _unsafe_rel(rel: str) -> bool:
    """True for absolute paths or anything that would leave the root."""
    norm = _normalize_rel(rel)
    if not norm or norm.startswith("/") or DRIVE_RE.match(norm):
        return True
    return any(part in {"", ".", ".."} for part in norm.split("/"))


def _under_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _file_exists(root: Path, rel: str) -> bool:
    """True if ``rel`` exists under ``root`` on disk. Git tracking does not matter."""
    if _unsafe_rel(rel):
        return False
    norm = _normalize_rel(rel)
    if any(char in norm for char in "*?["):
        try:
            matches = list(root.glob(norm))
        except ValueError:
            return False
        return any(path.exists() and _under_root(root, path) for path in matches)
    target = root.joinpath(*norm.split("/"))
    return target.exists() and _under_root(root, target)


def _file_findings(document: Document, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for entry in document.all_entries():
        for rel in entry.files:
            if not _file_exists(root, rel):
                findings.append(
                    _finding(
                        W103,
                        "warning",
                        entry.line,
                        f"[files: {rel}] matches nothing",
                        hint="fix the path or drop the file reference",
                    )
                )
    return findings


def _ledger_findings(document: Document, ledger_text: str) -> list[Finding]:
    if not ledger_text:
        return []
    ledger = ids_in_text(ledger_text)
    file_marks = ids_in_text("\n".join(item.raw or f"{item.id} {item.text}" for item in document.all_entries()))
    behind = [kind for kind in file_marks if file_marks[kind] > ledger.get(kind, 0)]
    if not behind:
        return []
    return [
        _finding(
            W106,
            "warning",
            0,
            "ID ledger behind the file; next: the next accept will rewrite .costanza/archive/ids",
            path=".costanza/archive/ids",
            hint="cz accept of any proposal rewrites the ledger",
        )
    ]


def _git_findings(document: Document, root: Path, stale_after: int) -> list[Finding]:
    info = probe(root)
    if not info.available or not info.repo:
        return []
    synced = document.header.synced.strip()
    if synced in {"", "never", "?"}:
        if has_commits(root):
            return [
                _finding(
                    W107,
                    "warning",
                    document.header.line,
                    "synced is never in a repo with commits",
                    hint="cz sync",
                )
            ]
        return []
    sha = synced.split()[0] if synced.split() else ""
    if not SHA_RE.match(sha):
        return [
            _finding(
                W108,
                "warning",
                document.header.line,
                f"synced commit {sha} is not in history",
                hint="cz sync",
            )
        ]
    behind = commits_behind(root, sha)
    if behind is None:
        return [
            _finding(
                W108,
                "warning",
                document.header.line,
                f"synced commit {sha} is not in history",
                hint="cz sync",
            )
        ]
    if behind >= stale_after:
        return [
            _finding(
                W107,
                "warning",
                document.header.line,
                f"synced is {behind} commits behind HEAD (stale_after {stale_after})",
                hint="cz sync",
            )
        ]
    return []


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _inbox_findings(paths: ProjectPaths, warn_days: int) -> list[Finding]:
    inbox = load_inbox(paths.inbox)
    now = datetime.now(timezone.utc)
    findings: list[Finding] = []
    for item in inbox.proposed():
        stamp = _parse_ts(item.ts)
        if stamp is None:
            continue
        age = (now - stamp).total_seconds() / 86400
        if age >= warn_days:
            findings.append(
                _finding(
                    W109,
                    "warning",
                    item.line,
                    f"{item.id} has been proposed for {int(age)} days",
                    path=".costanza/inbox.jsonl",
                    hint="cz review",
                )
            )
    return findings


def _resemble_findings(document: Document) -> list[Finding]:
    rejected = [(item, hash_norm(item.text)) for item in document.rejected]
    if not rejected:
        return []
    import difflib

    findings: list[Finding] = []
    for decision in document.decisions:
        needle = hash_norm(decision.text)
        for rejected_item, rejected_norm in rejected:
            if needle == rejected_norm or difflib.SequenceMatcher(None, needle, rejected_norm).ratio() >= NEAR_RATIO:
                findings.append(
                    _finding(
                        W110,
                        "warning",
                        decision.line,
                        f"{decision.id} resembles rejected {rejected_item.id}",
                        hint="confirm the decision still stands, or archive one of them",
                    )
                )
                break
    return findings


def _extra_secret_files(paths: ProjectPaths) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if paths.config.is_file():
        out.append((".costanza/config.toml", paths.config))
    if paths.archive_dir.is_dir():
        for path in sorted(paths.archive_dir.iterdir()):
            if path.is_file():
                rel = f".costanza/archive/{path.name}"
                out.append((rel, path))
    return out


def collect_findings(
    document: Document,
    text: str,
    paths: ProjectPaths,
    config: Config,
) -> list[Finding]:
    findings = list(validate(document))
    findings.extend(_budget_findings(active_count(text), config))
    allow = list(config.secret_allow)
    findings.extend(_secret_findings(text, "COSTANZA.md", allow))
    for rel, path in _extra_secret_files(paths):
        findings.extend(_secret_findings(read_text(path), rel, allow))
    findings.extend(_file_findings(document, paths.root))
    ledger = read_text(paths.ledger) if paths.ledger.is_file() else ""
    findings.extend(_ledger_findings(document, ledger))
    findings.extend(_git_findings(document, paths.root, config.stale_after))
    findings.extend(_inbox_findings(paths, config.warn_days))
    findings.extend(_resemble_findings(document))
    findings.sort(key=lambda item: (item.path, item.line, item.code, item.message))
    return findings


def run_check(
    cwd: Path | None = None,
    explicit: Path | None = None,
    *,
    fix: bool = False,
) -> tuple[CheckReport, Config]:
    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    if not paths.file.is_file():
        raise NotFoundError(
            f"no COSTANZA.md found from {(cwd or Path.cwd()).resolve()} upward",
            "cz init",
        )
    config = load_config(paths.config)
    bind(config.tokenizer, config.tokenizer_encoding, config.tokenizer_cache, root)
    text = read_text(paths.file)
    document = parse(text)
    fixed = False
    if fix and document.readable and document.marker_ok and document.version == 1:
        canonical = render(document)
        if canonical != text.replace("\r\n", "\n").replace("\r", "\n"):
            mutate_file(paths, text, lambda current: current, "check --fix")
            text = read_text(paths.file)
            document = parse(text)
            fixed = True
    findings = collect_findings(document, text, paths, config)
    report = CheckReport(
        root=root,
        findings=findings,
        tokens=active_count(text),
        budget=config.budget_tokens,
        document=document,
        fixed=fixed,
    )
    return report, config
