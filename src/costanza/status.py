"""Build the status view from whatever exists (Step 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from costanza.cf1 import Document, Problem, parse
from costanza.config import Config, load_config
from costanza.constants import HEADER_KEYS, KINDS, NOW_KEYS
from costanza.estimate import budget_state
from costanza.exceptions import NotFoundError, ParseError
from costanza.inbox import count_proposed
from costanza.io import read_text
from costanza.paths import ProjectPaths, discover_root
from costanza.tokens import bind, measure


@dataclass
class StatusView:
    root: Path
    project: str
    tokens: int
    budget: int
    ratio: float
    state: str
    estimator: str
    counts: dict[str, int]
    proposed: int
    now: dict[str, str]
    header: dict[str, str]
    synced_sha: str | None
    synced_date: str | None
    behind: int | None = None
    git_repo: bool = False
    git_commits: bool = False
    problems: list[Problem] = field(default_factory=list)
    next_hint: str | None = None

    @property
    def percent(self) -> int:
        if self.budget <= 0:
            return 0
        return round(100 * self.tokens / self.budget)

    @property
    def short_name(self) -> str:
        head, _, _ = self.project.partition(",")
        return head.strip() or self.project

    def to_json(self) -> dict[str, Any]:
        synced: dict[str, str] | None
        if self.synced_sha and self.synced_date:
            synced = {"sha": self.synced_sha, "date": self.synced_date}
        else:
            synced = None
        behind: int | None
        if self.synced_sha and self.git_repo:
            behind = self.behind
        else:
            behind = None
        header = {key: self.header.get(key, "?") for key in ("stack", "run", "test", "layout")}
        return {
            "root": str(self.root).replace("\\", "/"),
            "project": self.project,
            "tokens": self.tokens,
            "budget": self.budget,
            "ratio": self.ratio,
            "state": self.state,
            "estimator": self.estimator,
            "counts": {kind: self.counts.get(kind, 0) for kind in KINDS},
            "inbox": {"proposed": self.proposed},
            "now": {key: self.now.get(key, "none") for key in NOW_KEYS},
            "header": header,
            "synced": synced,
            "behind": behind,
            "problems": [
                {"line": item.line, "code": item.code, "message": item.message}
                for item in self.problems
            ],
        }


def read_status(
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> tuple[StatusView, Config]:
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
    doc = parse(text)
    if not doc.readable:
        problem = doc.problems[0] if doc.problems else Problem(1, "E001", "unreadable")
        raise ParseError(
            f"COSTANZA.md line {problem.line}: {problem.message}",
            "fix that line, then cz check",
        )
    return build_view(root, text, doc, config, count_proposed(paths.inbox)), config


def build_view(
    root: Path,
    text: str,
    doc: Document,
    config: Config,
    proposed: int,
) -> StatusView:
    tokens, method = measure(text)
    budget = config.budget_tokens
    ratio = round(tokens / budget, 3) if budget else 0.0
    state = budget_state(tokens, budget, config.warn_at)
    sha, date = _parse_synced(doc.header.get("synced", "never"))
    git_repo, git_commits, behind = _git_drift(root, sha)
    view = StatusView(
        root=root,
        project=doc.project,
        tokens=tokens,
        budget=budget,
        ratio=ratio,
        state=state,
        estimator=method,
        counts=doc.counts,
        proposed=proposed,
        now={key: doc.now.get(key, "none") for key in NOW_KEYS},
        header={
            key: doc.header.get(key, "?" if key != "synced" else "never") for key in HEADER_KEYS
        },
        synced_sha=sha,
        synced_date=date,
        behind=behind,
        git_repo=git_repo,
        git_commits=git_commits,
        problems=list(doc.problems),
    )
    view.next_hint = _next_hint(view)
    return view


def _git_drift(root: Path, sha: str | None) -> tuple[bool, bool, int | None]:
    from costanza.git import commits_behind, has_commits, probe

    info = probe(root)
    if not info.available or not info.repo:
        return False, False, None
    commits = has_commits(root)
    if not commits or not sha:
        return True, commits, None
    return True, True, commits_behind(root, sha)


def _parse_synced(value: str) -> tuple[str | None, str | None]:
    if value in {"", "never", "?"}:
        return None, None
    parts = value.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def _next_hint(view: StatusView) -> str | None:
    if view.problems:
        return "cz check"
    if view.state == "over":
        return "cz compact"
    if view.proposed:
        return f"cz review ({view.proposed} proposals waiting)"
    if view.git_commits and (view.synced_sha is None or (view.behind or 0) > 0):
        return "cz sync"
    for key in ("stack", "run", "test", "layout"):
        if view.header.get(key, "?") == "?":
            return "edit the header in COSTANZA.md"
    return None
