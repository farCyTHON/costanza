"""Set COSTANZA.md ``synced`` to the current HEAD."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from costanza import gate
from costanza.config import Config, load_config
from costanza.exceptions import UsageError
from costanza.format import Document
from costanza.git import commit_exists, diff_names, git_gap, head
from costanza.paths import ProjectPaths, discover_root
from costanza.store import mutate_file, read_file


@dataclass
class SyncNotice:
    entry_id: str
    message: str


@dataclass
class SyncResult:
    sha: str
    date: str
    previous: str
    applied: bool
    notices: list[SyncNotice]
    skipped_history: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "sha": self.sha,
            "date": self.date,
            "previous": self.previous,
            "applied": self.applied,
        }


def _notices(document: Document, root: Path, old_sha: str | None) -> tuple[list[SyncNotice], bool]:
    if old_sha is None:
        return [], False
    if not commit_exists(root, old_sha):
        return [], True
    changed = diff_names(root, old_sha)
    if changed is None:
        return [], True
    changed_set = set(changed)
    notices: list[SyncNotice] = []
    behind = None
    from costanza.git import commits_behind

    behind = commits_behind(root, old_sha)
    for entry in document.all_entries():
        for rel in entry.files:
            path = root.joinpath(*rel.replace("\\", "/").split("/"))
            exists = path.exists()
            if rel in changed_set:
                count = behind if behind is not None else 0
                notices.append(
                    SyncNotice(
                        entry_id=entry.id,
                        message=(
                            f"{entry.id} references {rel}, changed in {count} commits "
                            f"since {old_sha}. Still true?"
                        ),
                    )
                )
            elif not exists:
                notices.append(
                    SyncNotice(
                        entry_id=entry.id,
                        message=f"{entry.id} references {rel}, which no longer exists.",
                    )
                )
    return notices, False


def sync_file(
    *,
    apply: bool,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> tuple[SyncResult, Config]:
    root = discover_root(cwd, explicit, allow_cwd=False)
    gap = git_gap(root)
    if gap:
        raise UsageError(gap, "git init is enough; no remote is needed")
    sha, date = head(root)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    previous, document = read_file(paths)
    old = document.header.synced
    old_sha = None if old in {"", "never", "?"} else old.split()[0]
    notices, skipped = _notices(document, root, old_sha)
    value = f"{sha} {date}"
    if not apply:
        return (
            SyncResult(
                sha=sha,
                date=date,
                previous=old,
                applied=False,
                notices=notices,
                skipped_history=skipped,
            ),
            config,
        )
    if not gate.confirm(f"mark COSTANZA.md synced to {sha} {date}?"):
        return (
            SyncResult(
                sha=sha,
                date=date,
                previous=old,
                applied=False,
                notices=notices,
                skipped_history=skipped,
            ),
            config,
        )

    def mutator(current: Document) -> Document:
        header = replace(current.header, synced=value)
        return replace(current, header=header)

    mutate_file(paths, previous, mutator, f"synced {value}")
    return (
        SyncResult(
            sha=sha,
            date=date,
            previous=old,
            applied=True,
            notices=notices,
            skipped_history=skipped,
        ),
        config,
    )
