"""Create COSTANZA.md and .costanza/ (Step 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from costanza.constants import CONFIG_TEXT, IGNORE_COMMENT, IGNORE_LINES, LEDGER_TEXT, skeleton
from costanza.estimate import file_tokens
from costanza.exceptions import ExistsError, UsageError
from costanza.io import copy_bytes, read_text, write_text
from costanza.paths import ProjectPaths, discover_root


@dataclass
class InitAction:
    verb: str
    path: str
    extra: str = ""


@dataclass
class InitResult:
    root: Path
    actions: list[InitAction] = field(default_factory=list)
    tokens: int = 0


def initialize(
    cwd: Path | None = None,
    explicit: Path | None = None,
    *,
    force: bool = False,
    name: str | None = None,
    agents: str = "auto",
) -> InitResult:
    root = discover_root(cwd, explicit, allow_cwd=True)
    paths = ProjectPaths(root)
    if paths.file.exists() and not force:
        raise ExistsError(
            f"COSTANZA.md already exists in {root}",
            "cz status, or cz init --force to replace it",
        )

    project_name = name if name is not None else root.name
    result = InitResult(root=root)

    if force and paths.file.exists():
        copy_bytes(paths.file, paths.file_bak)
        result.actions.append(InitAction("created", "COSTANZA.md.bak"))
    if force and paths.config.exists():
        copy_bytes(paths.config, paths.config_bak)
        result.actions.append(InitAction("created", ".costanza/config.toml.bak"))

    text = skeleton(project_name)
    write_text(paths.file, text)
    result.tokens = file_tokens(text)
    result.actions.append(InitAction("created", "COSTANZA.md", f"~{result.tokens} tokens"))

    if paths.config.exists() and not force:
        result.actions.append(InitAction("kept", ".costanza/config.toml"))
    else:
        write_text(paths.config, CONFIG_TEXT)
        result.actions.append(InitAction("created", ".costanza/config.toml"))

    paths.archive_dir.mkdir(parents=True, exist_ok=True)
    if not paths.ledger.exists():
        write_text(paths.ledger, LEDGER_TEXT)
        result.actions.append(InitAction("created", ".costanza/archive/ids"))

    if paths.is_git_repo():
        added = ensure_gitignore(paths.gitignore)
        if added:
            result.actions.append(InitAction("updated", ".gitignore", f"+{added} lines"))

    mode = (agents or "auto").strip().lower()
    if mode not in {"auto", "all", "none"}:
        raise UsageError(
            "agents mode must be auto, all or none",
            "cz init --agents auto",
        )
    if mode != "none":
        from costanza.agents import install_agents

        agent_result = install_agents(mode=mode, explicit=root)
        verbs = {
            "created": "created",
            "installed": "updated",
            "unchanged": "kept",
            "failed": "failed",
            "newer": "kept",
            "missing": "kept",
        }
        for row in agent_result.rows:
            if row.path == "(none)":
                continue
            result.actions.append(
                InitAction(verbs.get(row.status, row.status), row.path, row.detail)
            )

    return result


def ensure_gitignore(path: Path) -> int:
    existing_lines = read_text(path).splitlines() if path.exists() else []
    existing = set(existing_lines)
    missing = [line for line in IGNORE_LINES if line not in existing]
    if not missing:
        return 0
    out = list(existing_lines)
    if out and out[-1].strip() != "":
        out.append("")
    if IGNORE_COMMENT not in existing:
        out.append(IGNORE_COMMENT)
    out.extend(missing)
    write_text(path, "\n".join(out) + "\n")
    return len(missing)
