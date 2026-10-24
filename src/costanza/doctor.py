"""Installation health. Reports data; ui.py prints it.

``--fix`` removes a stale lock, adds missing gitignore lines, and raises
the ledger without asking. Renumbering a duplicate ID goes through
``gate.confirm``. A lock younger than 30 seconds is a warning and is
left in place.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from costanza import gate
from costanza.agents import status_agents
from costanza.config import Config, load_config
from costanza.constants import IGNORE_LINES, KINDS
from costanza.exceptions import ConfigError, NotFoundError, ParseError, UsageError
from costanza.format import CF006, Document, Entry, high_water, parse, validate
from costanza.hooks import hook_status
from costanza.inbox import load_inbox
from costanza.init import ensure_gitignore
from costanza.io import read_text
from costanza.lock import STALE_SECONDS, hold_lock
from costanza.paths import ProjectPaths, explicit_root, resolve_existing_dir
from costanza.store import archive_texts, mutate_file, read_file, write_ledger

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]  # tomli has no stubs; used on 3.10 only

CHECK_NAMES = (
    "python",
    "git",
    "root",
    "parse",
    "config",
    "inbox",
    "lock",
    "gitignore",
    "hook",
    "agents",
    "duplicates",
    "ledger",
    "encoding",
    "extras",
)

_KNOWN: dict[str, frozenset[str] | None] = {
    "version": None,
    "budget": frozenset(
        {
            "tokens",
            "warn_at",
            "compact_target",
            "auto_compact",
            "tokenizer",
            "tokenizer_encoding",
            "tokenizer_cache",
        }
    ),
    "format": frozenset({"soft_line_limit", "entry_sha"}),
    "inbox": frozenset({"max_open", "retain_days", "purge_days", "warn_days"}),
    "git": frozenset({"apply_trailers", "stamp_commits", "stale_after"}),
    "scan": frozenset({"exclude"}),
    "secrets": frozenset({"allow", "extra_patterns"}),
    "agents": frozenset({"targets"}),
    "import": frozenset({"max_bytes"}),
    "ui": frozenset({"color", "ascii"}),
}

_TTY_SKIP = "duplicate IDs need cz doctor --fix in your own terminal"


@dataclass
class DoctorCheck:
    name: str
    status: str
    detail: str
    next: str | None = None


@dataclass
class DoctorReport:
    checks: list[DoctorCheck]
    notes: list[str]
    color_policy: str = "auto"
    ascii_policy: str = "auto"

    @property
    def failed(self) -> bool:
        return any(item.status == "fail" for item in self.checks)

    def to_json(self) -> dict[str, Any]:
        return {
            "checks": [
                {
                    "name": item.name,
                    "status": item.status,
                    "detail": item.detail,
                    "next": item.next,
                }
                for item in self.checks
            ]
        }


def run_doctor(
    *,
    cwd: Path | None = None,
    explicit: Path | None = None,
    fix: bool = False,
    version: tuple[int, int] | None = None,
    encoding: str | None = None,
) -> DoctorReport:
    """Run every doctor check. ``fix`` applies only the repairs in section 5.4."""
    root, how = _locate(explicit, cwd)
    paths = ProjectPaths(root)
    notes: list[str] = []
    if fix:
        notes.extend(_apply_fixes(paths))
    config, raw, config_error = _load(paths)
    checks = [
        _python_check(version or (sys.version_info[0], sys.version_info[1])),
        _git_check(),
        DoctorCheck("root", "ok", f"{root} via {how}"),
        *_file_checks(paths, raw, config_error),
        _encoding_check(config.ascii, encoding),
        _extras_check(paths.root, raw),
    ]
    return DoctorReport(
        checks=checks,
        notes=notes,
        color_policy=config.color,
        ascii_policy=config.ascii,
    )


def _locate(explicit: Path | None, cwd: Path | None) -> tuple[Path, str]:
    flagged = explicit_root(explicit)
    if flagged is not None:
        how = "--root" if explicit is not None else "COSTANZA_ROOT"
        return resolve_existing_dir(flagged), how
    start = (cwd or Path.cwd()).resolve()
    for path in [start, *start.parents]:
        if (path / "COSTANZA.md").exists():
            return path, "COSTANZA.md"
        if (path / ".costanza").exists():
            return path, ".costanza/"
    for path in [start, *start.parents]:
        if (path / ".git").exists():
            return path, ".git"
    raise NotFoundError(
        f"no COSTANZA.md found from {start} upward",
        "cz init",
    )


def _load(paths: ProjectPaths) -> tuple[Config, dict[str, Any] | None, str | None]:
    raw: dict[str, Any] | None
    try:
        if paths.config.is_file():
            loaded = tomllib.loads(read_text(paths.config))
            raw = loaded if isinstance(loaded, dict) else None
        else:
            raw = {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raw = None
    try:
        return load_config(paths.config), raw, None
    except ConfigError as exc:
        return Config(), raw, exc.message


def _apply_fixes(paths: ProjectPaths) -> list[str]:
    notes: list[str] = []
    age = _lock_age(paths.lock)
    if age is not None and age > STALE_SECONDS:
        try:
            paths.lock.unlink()
        except OSError:
            notes.append("could not remove .costanza/lock")
    if paths.is_git_repo():
        ensure_gitignore(paths.gitignore)
    if _lock_age(paths.lock) is not None:
        notes.append("lock is in use; COSTANZA.md and the ledger were left unchanged")
        return notes
    try:
        text, document = read_file(paths)
    except (NotFoundError, ParseError, OSError, UnicodeError):
        return notes
    duplicates = _duplicate_entries(document)
    if duplicates:
        made = _renumber(document, archive_texts(paths))[1]
        if made:
            try:
                allowed = gate.confirm(
                    f"renumber {len(made)} duplicate ID(s) in COSTANZA.md? " + "; ".join(made)
                )
            except UsageError:
                notes.append(_TTY_SKIP)
                allowed = False
            if allowed:
                captured: list[str] = []

                def mutator(current: Document) -> Document:
                    updated, lines = _renumber(current, archive_texts(paths))
                    captured.extend(lines)
                    return updated

                mutate_file(paths, text, mutator, "doctor renumbered duplicate IDs")
                notes.extend(captured or made)
                return notes
            if _TTY_SKIP not in notes:
                notes.append("duplicate IDs were left unchanged")
    _raise_ledger(paths, document)
    return notes


def _raise_ledger(paths: ProjectPaths, document: Document) -> None:
    with hold_lock(paths):
        write_ledger(paths, document)


def _file_checks(
    paths: ProjectPaths,
    raw: dict[str, Any] | None,
    config_error: str | None,
) -> list[DoctorCheck]:
    document, parse_check = _parse_check(paths)
    return [
        parse_check,
        _config_check(raw, config_error),
        _inbox_check(paths),
        _lock_check(paths),
        _gitignore_check(paths),
        _hook_check(paths.root),
        _agents_check(paths.root),
        _duplicate_check(document),
        _ledger_check(paths, document),
    ]


def _python_check(version: tuple[int, int]) -> DoctorCheck:
    shown = ".".join(str(part) for part in version)
    if version[0] == 3 and 10 <= version[1] <= 13:
        detail = sys.version.split()[0] if version == (sys.version_info[0], sys.version_info[1]) else shown
        return DoctorCheck("python", "ok", detail)
    return DoctorCheck(
        "python",
        "fail",
        f"{shown} is outside 3.10 to 3.13",
        "use Python 3.10 to 3.13",
    )


def _git_check() -> DoctorCheck:
    from costanza.git import git_executable

    if git_executable() is None:
        return DoctorCheck("git", "warn", "git not found on PATH", "install git to use cz sync and cz hook")
    return DoctorCheck("git", "ok", "git found")


def _parse_check(paths: ProjectPaths) -> tuple[Document | None, DoctorCheck]:
    if not paths.file.is_file():
        return None, DoctorCheck("parse", "fail", "COSTANZA.md is missing", "cz init")
    try:
        document = parse(read_text(paths.file))
    except (OSError, UnicodeError) as exc:
        return None, DoctorCheck("parse", "fail", str(exc), "cz check")
    errors = [
        item for item in validate(document) if item.severity == "error" and item.code != CF006
    ]
    if errors:
        return document, DoctorCheck(
            "parse",
            "fail",
            f"{len(errors)} structural error(s); {errors[0].message}",
            "cz check",
        )
    return document, DoctorCheck("parse", "ok", "valid")


def _config_check(raw: dict[str, Any] | None, config_error: str | None) -> DoctorCheck:
    names = _pattern_names(raw)
    extra = f"; extra patterns: {', '.join(names)}" if names else ""
    if config_error is not None:
        return DoctorCheck(
            "config",
            "fail",
            config_error + extra,
            "fix the value or delete the key to use the default",
        )
    unknown = _unknown_keys(raw or {})
    if unknown:
        listed = ", ".join(unknown)
        return DoctorCheck("config", "warn", f"unknown keys: {listed}{extra}", "delete the unknown keys")
    detail = "valid" + extra
    return DoctorCheck("config", "ok", detail)


def _pattern_names(raw: dict[str, Any] | None) -> list[str]:
    if not raw:
        return []
    secrets = raw.get("secrets")
    if not isinstance(secrets, dict):
        return []
    patterns = secrets.get("extra_patterns")
    if not isinstance(patterns, list):
        return []
    names: list[str] = []
    for item in patterns:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


def _unknown_keys(data: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key, value in data.items():
        if key not in _KNOWN:
            found.append(str(key))
            continue
        allowed = _KNOWN[key]
        if allowed is None or not isinstance(value, dict):
            continue
        for child in value:
            if child not in allowed:
                found.append(f"{key}.{child}")
    return found


def _inbox_check(paths: ProjectPaths) -> DoctorCheck:
    warnings = list(load_inbox(paths.inbox).warnings())
    for warning in load_inbox(paths.inbox_archive).warnings():
        warnings.append(warning.replace("inbox.jsonl", "inbox-archive.jsonl", 1))
    if not warnings:
        return DoctorCheck("inbox", "ok", "no ignored lines")
    shown = "; ".join(warnings[:3])
    if len(warnings) > 3:
        shown += f"; and {len(warnings) - 3} more"
    return DoctorCheck("inbox", "warn", shown, "fix or delete the ignored inbox lines")


def _lock_check(paths: ProjectPaths) -> DoctorCheck:
    age = _lock_age(paths.lock)
    if age is None:
        return DoctorCheck("lock", "ok", "no lock")
    seconds = int(age)
    if age > STALE_SECONDS:
        return DoctorCheck("lock", "fail", f"stale lock ({seconds}s)", "cz doctor --fix")
    return DoctorCheck("lock", "warn", f"lock is {seconds}s old and was left in place")


def _lock_age(path: Path) -> float | None:
    if not path.exists():
        return None
    text = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        if not line.startswith("ts="):
            continue
        raw = line[3:].strip().replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            break
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - stamp).total_seconds()
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return STALE_SECONDS + 1


def _gitignore_check(paths: ProjectPaths) -> DoctorCheck:
    if not paths.is_git_repo():
        return DoctorCheck("gitignore", "ok", "not a git repo")
    missing = _missing_ignore(paths.gitignore)
    if missing:
        return DoctorCheck("gitignore", "fail", f"missing {', '.join(missing)}", "cz doctor --fix")
    return DoctorCheck("gitignore", "ok", "present")


def _missing_ignore(path: Path) -> list[str]:
    if not path.is_file():
        return list(IGNORE_LINES)
    existing = set(read_text(path).splitlines())
    return [line for line in IGNORE_LINES if line not in existing]


def _hook_check(root: Path) -> DoctorCheck:
    try:
        report = hook_status(root)
    except ConfigError as exc:
        return DoctorCheck("hook", "warn", exc.message, "cz hook status")
    if report.state in {"installed", "unchanged"}:
        return DoctorCheck("hook", "ok", report.state)
    hint = "cz hook install" if report.state == "missing" else "cz hook status"
    return DoctorCheck("hook", "warn", report.state, hint)


def _agents_check(root: Path) -> DoctorCheck:
    try:
        result = status_agents(explicit=root)
    except ConfigError as exc:
        return DoctorCheck("agents", "warn", exc.message, "cz agents")
    bad = [row for row in result.rows if row.status not in {"installed", "unchanged"}]
    if not bad:
        return DoctorCheck("agents", "ok", "current")
    detail = "; ".join(f"{row.path} {row.status}" for row in bad)
    return DoctorCheck("agents", "warn", detail, "cz agents")


def _duplicate_entries(document: Document) -> list[Entry]:
    seen: set[str] = set()
    found: list[Entry] = []
    for entry in document.all_entries():
        if entry.id in seen:
            found.append(entry)
        else:
            seen.add(entry.id)
    return found


def _duplicate_check(document: Document | None) -> DoctorCheck:
    if document is None:
        return DoctorCheck("duplicates", "ok", "no file")
    found = _duplicate_entries(document)
    if not found:
        return DoctorCheck("duplicates", "ok", "none")
    first = found[0]
    return DoctorCheck(
        "duplicates",
        "fail",
        f"{first.id} also at line {first.line}",
        "cz doctor --fix",
    )


def _ledger_check(paths: ProjectPaths, document: Document | None) -> DoctorCheck:
    if document is None:
        return DoctorCheck("ledger", "ok", "no file")
    if not paths.ledger.is_file():
        return DoctorCheck("ledger", "warn", "ledger is missing", "cz doctor --fix")
    try:
        ledger = read_text(paths.ledger)
    except (OSError, UnicodeError) as exc:
        return DoctorCheck("ledger", "warn", str(exc), "cz doctor --fix")
    from costanza.format import ids_in_text

    marks = ids_in_text(ledger)
    file_marks = {kind: 0 for kind in KINDS}
    for entry in document.all_entries():
        file_marks[entry.kind] = max(file_marks[entry.kind], entry.number)
    behind = [kind for kind in KINDS if file_marks[kind] > marks.get(kind, 0)]
    if behind:
        return DoctorCheck("ledger", "warn", f"behind: {', '.join(behind)}", "cz doctor --fix")
    return DoctorCheck("ledger", "ok", "matches")


def _encoding_check(policy: str, encoding: str | None) -> DoctorCheck:
    encoding = encoding or ""
    if not encoding:
        return DoctorCheck("encoding", "warn", "stdout encoding is unknown")
    mode = "ascii" if _ascii_on(policy, encoding) else "unicode"
    return DoctorCheck("encoding", "ok", f"{encoding}; {mode}")


def _ascii_on(policy: str, encoding: str) -> bool:
    if os.environ.get("COSTANZA_ASCII") == "1" or policy == "always":
        return True
    if os.environ.get("COSTANZA_ASCII") == "0" or policy == "never":
        return False
    try:
        "✓█░→…".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return True
    return False


def _extras_check(root: Path, raw: dict[str, Any] | None) -> DoctorCheck:
    mcp = importlib.util.find_spec("mcp") is not None
    tokens = importlib.util.find_spec("tiktoken") is not None
    budget: dict[str, Any] = {}
    if isinstance(raw, dict) and isinstance(raw.get("budget"), dict):
        budget = raw["budget"]
    tokenizer = budget.get("tokenizer", "estimate")
    cache = budget.get("tokenizer_cache", "")
    parts = [
        f"mcp {'installed' if mcp else 'not installed'}",
        f"tiktoken {'installed' if tokens else 'not installed'}",
        f"tokenizer {tokenizer}",
    ]
    if tokenizer != "tiktoken":
        return DoctorCheck("extras", "ok", "; ".join(parts))
    cache_path = _cache_dir(root, cache if isinstance(cache, str) else "")
    seeded = cache_path is not None and cache_path.is_dir() and any(cache_path.iterdir())
    hint = (
        "seed the tokenizer cache by hand outside Costanza, set budget.tokenizer_cache, "
        "and install costanza[tokens]; Costanza never downloads encodings"
    )
    if not tokens or not seeded:
        return DoctorCheck("extras", "warn", "; ".join(parts), hint)
    return DoctorCheck("extras", "ok", "; ".join(parts) + "; cache seeded")


def _cache_dir(root: Path, cache: str) -> Path | None:
    if not cache:
        return None
    path = Path(cache)
    if not path.is_absolute():
        path = root / path
    return path


def _rewrite(
    entries: tuple[Entry, ...],
    kind: str,
    seen: set[str],
    water: dict[str, int],
    notes: list[str],
) -> tuple[Entry, ...]:
    rows: list[Entry] = []
    for entry in entries:
        if entry.id not in seen:
            seen.add(entry.id)
            rows.append(entry)
            continue
        water[kind] += 1
        new_id = f"{kind}{water[kind]}"
        while new_id in seen:
            water[kind] += 1
            new_id = f"{kind}{water[kind]}"
        notes.append(
            f"{entry.id} (line {entry.line}) → {new_id}; "
            f"references to {entry.id} in text were not changed"
        )
        rows.append(replace(entry, number=water[kind]))
        seen.add(new_id)
    return tuple(rows)


def _renumber(document: Document, archives: list[str]) -> tuple[Document, list[str]]:
    water = high_water(document, *archives)
    seen: set[str] = set()
    notes: list[str] = []
    updated = replace(
        document,
        decisions=_rewrite(document.decisions, "D", seen, water, notes),
        rejected=_rewrite(document.rejected, "X", seen, water, notes),
        rules=_rewrite(document.rules, "R", seen, water, notes),
        gotchas=_rewrite(document.gotchas, "G", seen, water, notes),
        open=_rewrite(document.open, "Q", seen, water, notes),
    )
    return updated, notes
