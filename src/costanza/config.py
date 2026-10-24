"""Load .costanza/config.toml. Missing file means defaults."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from costanza.constants import (
    DEFAULT_BUDGET,
    DEFAULT_COMPACT_TARGET,
    DEFAULT_IMPORT_MAX_BYTES,
    DEFAULT_PURGE_DAYS,
    DEFAULT_RETAIN_DAYS,
    DEFAULT_SCAN_EXCLUDE,
    DEFAULT_STALE_AFTER,
    DEFAULT_WARN_AT,
    DEFAULT_WARN_DAYS,
)
from costanza.exceptions import ConfigError
from costanza.io import read_text

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]  # tomli has no stubs; used on 3.10 only


@dataclass(frozen=True)
class Config:
    budget_tokens: int = DEFAULT_BUDGET
    warn_at: float = DEFAULT_WARN_AT
    compact_target: float = DEFAULT_COMPACT_TARGET
    auto_compact: bool = False
    color: str = "auto"
    ascii: str = "auto"
    max_open: int = 100
    retain_days: int = DEFAULT_RETAIN_DAYS
    purge_days: int = DEFAULT_PURGE_DAYS
    warn_days: int = DEFAULT_WARN_DAYS
    entry_sha: bool = True
    stale_after: int = DEFAULT_STALE_AFTER
    scan_exclude: tuple[str, ...] = DEFAULT_SCAN_EXCLUDE
    secret_allow: tuple[str, ...] = ()
    agents_targets: tuple[str, ...] = ()
    apply_trailers: bool = True
    stamp_commits: bool = True
    import_max_bytes: int = DEFAULT_IMPORT_MAX_BYTES
    tokenizer: str = "estimate"
    tokenizer_encoding: str = "o200k_base"
    tokenizer_cache: str = ""


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if value == {} or value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            f".costanza/config.toml: [{name}] must be a table",
            "fix the value or delete the key to use the default",
        )
    return value


def _int(table: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    if key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f".costanza/config.toml: {key} must be an integer (got {value!r})",
            "fix the value or delete the key to use the default",
        )
    if value < low or value > high:
        raise ConfigError(
            f".costanza/config.toml: {key} must be between {low} and {high} (got {value})",
            "fix the value or delete the key to use the default",
        )
    return value


def _float(table: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    if key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f".costanza/config.toml: {key} must be a number (got {value!r})",
            "fix the value or delete the key to use the default",
        )
    number = float(value)
    if number < low or number > high:
        raise ConfigError(
            f".costanza/config.toml: {key} must be between {low:.2f} and {high:.2f} (got {number})",
            "fix the value or delete the key to use the default",
        )
    return number


def _bool(table: dict[str, Any], key: str, default: bool) -> bool:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f".costanza/config.toml: {key} must be true or false (got {value!r})",
            "fix the value or delete the key to use the default",
        )
    return value


def _text(table: dict[str, Any], key: str, default: str) -> str:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, str):
        raise ConfigError(
            f".costanza/config.toml: {key} must be a string (got {value!r})",
            "fix the value or delete the key to use the default",
        )
    return value


def _choice(table: dict[str, Any], key: str, default: str, allowed: frozenset[str]) -> str:
    if key not in table:
        return default
    value = table[key]
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(
            f".costanza/config.toml: {key} must be one of {sorted(allowed)} (got {value!r})",
            "fix the value or delete the key to use the default",
        )
    return value


def load_config(path: Path) -> Config:
    """Return defaults when ``path`` is missing."""
    if not path.is_file():
        return Config()
    try:
        data = tomllib.loads(read_text(path))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f".costanza/config.toml: {exc}",
            "fix the value or delete the key to use the default",
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            ".costanza/config.toml: root must be a table",
            "fix the value or delete the key to use the default",
        )
    budget = _table(data, "budget")
    ui = _table(data, "ui")
    inbox = _table(data, "inbox")
    fmt = _table(data, "format")
    secrets = _table(data, "secrets")
    allow = secrets.get("allow", [])
    if allow == [] or allow is None:
        allow_tuple: tuple[str, ...] = ()
    elif isinstance(allow, list) and all(isinstance(item, str) for item in allow):
        allow_tuple = tuple(allow)
    else:
        raise ConfigError(
            ".costanza/config.toml: secrets.allow must be a list of strings",
            "fix the value or delete the key to use the default",
        )
    git = _table(data, "git")
    scan = _table(data, "scan")
    agents = _table(data, "agents")
    imported = _table(data, "import")
    raw_targets = agents.get("targets", [])
    if raw_targets == [] or raw_targets is None:
        agents_targets: tuple[str, ...] = ()
    elif isinstance(raw_targets, list) and all(isinstance(item, str) for item in raw_targets):
        agents_targets = tuple(raw_targets)
    else:
        raise ConfigError(
            ".costanza/config.toml: agents.targets must be a list of strings",
            "fix the value or delete the key to use the default",
        )
    exclude = scan.get("exclude", list(DEFAULT_SCAN_EXCLUDE))
    if exclude is None:
        exclude_tuple = DEFAULT_SCAN_EXCLUDE
    elif isinstance(exclude, list) and all(isinstance(item, str) for item in exclude):
        exclude_tuple = tuple(exclude)
    else:
        raise ConfigError(
            ".costanza/config.toml: scan.exclude must be a list of strings",
            "fix the value or delete the key to use the default",
        )
    compact_target = _float(budget, "compact_target", DEFAULT_COMPACT_TARGET, 0.30, 1.00)
    warn_at = _float(budget, "warn_at", DEFAULT_WARN_AT, 0.50, 1.00)
    if compact_target > warn_at:
        compact_target = warn_at
    return Config(
        budget_tokens=_int(budget, "tokens", DEFAULT_BUDGET, 200, 100000),
        warn_at=warn_at,
        compact_target=compact_target,
        auto_compact=_bool(budget, "auto_compact", False),
        color=_choice(ui, "color", "auto", frozenset({"auto", "always", "never"})),
        ascii=_choice(ui, "ascii", "auto", frozenset({"auto", "always", "never"})),
        max_open=_int(inbox, "max_open", 100, 1, 10000),
        retain_days=_int(inbox, "retain_days", DEFAULT_RETAIN_DAYS, 1, 36500),
        purge_days=_int(inbox, "purge_days", DEFAULT_PURGE_DAYS, 1, 36500),
        warn_days=_int(inbox, "warn_days", DEFAULT_WARN_DAYS, 1, 36500),
        entry_sha=_bool(fmt, "entry_sha", True),
        stale_after=_int(git, "stale_after", DEFAULT_STALE_AFTER, 1, 10000),
        scan_exclude=exclude_tuple,
        secret_allow=allow_tuple,
        agents_targets=agents_targets,
        apply_trailers=_bool(git, "apply_trailers", True),
        stamp_commits=_bool(git, "stamp_commits", True),
        import_max_bytes=_int(imported, "max_bytes", DEFAULT_IMPORT_MAX_BYTES, 1024, 52_428_800),
        tokenizer=_choice(budget, "tokenizer", "estimate", frozenset({"estimate", "tiktoken"})),
        tokenizer_encoding=_text(budget, "tokenizer_encoding", "o200k_base"),
        tokenizer_cache=_text(budget, "tokenizer_cache", ""),
    )
