"""Root discovery and well-known paths. Does not call git."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from costanza.exceptions import NotFoundError


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def file(self) -> Path:
        return self.root / "COSTANZA.md"

    @property
    def costanza_dir(self) -> Path:
        return self.root / ".costanza"

    @property
    def config(self) -> Path:
        return self.costanza_dir / "config.toml"

    @property
    def inbox(self) -> Path:
        return self.costanza_dir / "inbox.jsonl"

    @property
    def inbox_archive(self) -> Path:
        return self.costanza_dir / "inbox-archive.jsonl"

    @property
    def lock(self) -> Path:
        return self.costanza_dir / "lock"

    @property
    def backup_dir(self) -> Path:
        return self.costanza_dir / "backup"

    @property
    def file_write_bak(self) -> Path:
        return self.backup_dir / "COSTANZA.md.bak"

    @property
    def archive_dir(self) -> Path:
        return self.costanza_dir / "archive"

    @property
    def ledger(self) -> Path:
        return self.archive_dir / "ids"

    @property
    def gitignore(self) -> Path:
        return self.root / ".gitignore"

    @property
    def file_bak(self) -> Path:
        return self.root / "COSTANZA.md.bak"

    @property
    def config_bak(self) -> Path:
        return self.costanza_dir / "config.toml.bak"

    @property
    def hook_log(self) -> Path:
        return self.costanza_dir / "hook.log"

    def is_git_repo(self) -> bool:
        return (self.root / ".git").exists()


def explicit_root(flag: Path | None) -> Path | None:
    """``--root`` wins, then ``COSTANZA_ROOT``."""
    if flag is not None:
        return flag
    env = os.environ.get("COSTANZA_ROOT")
    if env:
        return Path(env)
    return None


def resolve_existing_dir(path: Path) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved = resolved.resolve()
    if not resolved.is_dir():
        raise NotFoundError(
            f"root is not a directory: {path}",
            "pass an existing directory to --root",
        )
    return resolved


def discover_root(
    cwd: Path | None = None,
    explicit: Path | None = None,
    *,
    allow_cwd: bool = False,
) -> Path:
    """Find the project root (spec section 5.2)."""
    flagged = explicit_root(explicit)
    if flagged is not None:
        return resolve_existing_dir(flagged)

    start = (cwd or Path.cwd()).resolve()
    for path in [start, *start.parents]:
        if (path / "COSTANZA.md").exists() or (path / ".costanza").exists():
            return path
    for path in [start, *start.parents]:
        if (path / ".git").exists():
            return path
    if allow_cwd:
        return start
    raise NotFoundError(
        f"no COSTANZA.md found from {start} upward",
        "cz init",
    )
