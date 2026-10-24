"""Append-only inbox.jsonl. Status changes rewrite the file atomically.

Two processes writing at once: ``hold_lock`` (exclusive-create of
``.costanza/lock``) serialises readers+writers on Windows, macOS and Linux.
The rewrite uses ``os.replace`` so a crash never leaves a half-written JSONL.
See ``lock.py`` for why this was chosen over flock.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from costanza.io import read_text, write_text
from costanza.lock import hold_lock
from costanza.paths import ProjectPaths
from costanza.text import content_hash

INBOX_KEYS = (
    "v",
    "id",
    "kind",
    "text",
    "why",
    "files",
    "source",
    "agent",
    "ts",
    "commit",
    "status",
    "hash",
    "entry",
    "decided",
    "resolves",
    "via",
    "suggested",
)
REQUIRED = ("v", "id", "kind", "text", "status", "hash")
STATUSES = frozenset({"proposed", "accepted", "rejected", "dismissed"})
SOURCES = frozenset({"cli", "paste", "mcp", "import"})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Proposal:
    id: str
    kind: str
    text: str
    why: str | None = None
    files: list[str] = field(default_factory=list)
    source: str = "cli"
    agent: str | None = None
    ts: str = ""
    commit: str | None = None
    status: str = "proposed"
    hash: str = ""
    entry: str | None = None
    decided: str | None = None
    resolves: str | None = None
    via: str | None = None
    suggested: str | None = None
    purged: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    line: int = 0
    landing: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "v": 1,
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "why": self.why,
            "files": list(self.files),
            "source": self.source,
            "agent": self.agent,
            "ts": self.ts,
            "commit": self.commit,
            "status": self.status,
            "hash": self.hash,
            "entry": self.entry,
            "decided": self.decided,
            "resolves": self.resolves,
            "via": self.via,
            "suggested": self.suggested,
        }
        data.update(self.extra)
        if self.purged:
            data["purged"] = True
        return data

    def to_line(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, separators=(",", ":"))


@dataclass
class InboxLine:
    raw: str
    proposal: Proposal | None
    warning: str | None = None


@dataclass
class Inbox:
    lines: list[InboxLine]

    def proposals(self) -> list[Proposal]:
        return [item.proposal for item in self.lines if item.proposal is not None]

    def proposed(self) -> list[Proposal]:
        return [item for item in self.proposals() if item.status == "proposed"]

    def by_id(self, pid: str) -> Proposal | None:
        for item in self.proposals():
            if item.id == pid:
                return item
        return None

    def next_pid(self) -> str:
        highest = 0
        for item in self.proposals():
            if item.id.startswith("p"):
                try:
                    highest = max(highest, int(item.id[1:]))
                except ValueError:
                    continue
        return f"p{highest + 1}"

    def warnings(self) -> list[str]:
        return [item.warning for item in self.lines if item.warning]


def _parse_line(raw: str, number: int) -> InboxLine:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return InboxLine(raw=raw, proposal=None, warning=f"inbox.jsonl line {number} ignored: not JSON")
    if not isinstance(obj, dict):
        return InboxLine(raw=raw, proposal=None, warning=f"inbox.jsonl line {number} ignored: not an object")
    missing = [key for key in REQUIRED if key not in obj]
    if missing:
        return InboxLine(
            raw=raw,
            proposal=None,
            warning=f"inbox.jsonl line {number} ignored: missing {', '.join(missing)}",
        )
    known = set(INBOX_KEYS) | {"purged"}
    extra = {key: value for key, value in obj.items() if key not in known}
    files = obj.get("files") or []
    if not isinstance(files, list):
        files = []
    proposal = Proposal(
        id=str(obj["id"]),
        kind=str(obj["kind"]),
        text=str(obj["text"]),
        why=obj.get("why"),
        files=[str(item) for item in files],
        source=str(obj.get("source") or "cli"),
        agent=obj.get("agent"),
        ts=str(obj.get("ts") or ""),
        commit=obj.get("commit"),
        status=str(obj.get("status") or "proposed"),
        hash=str(obj["hash"]),
        entry=obj.get("entry"),
        decided=obj.get("decided"),
        resolves=obj.get("resolves"),
        via=obj.get("via"),
        suggested=obj.get("suggested"),
        purged=bool(obj.get("purged")),
        extra=extra,
        line=number,
    )
    if proposal.why is not None:
        proposal.why = str(proposal.why)
    return InboxLine(raw=raw, proposal=proposal)


def load_inbox(path: Path) -> Inbox:
    if not path.is_file():
        return Inbox(lines=[])
    lines: list[InboxLine] = []
    for number, raw in enumerate(read_text(path).splitlines(), start=1):
        if not raw.strip():
            continue
        lines.append(_parse_line(raw, number))
    return Inbox(lines=lines)


def dump_inbox(inbox: Inbox) -> str:
    out: list[str] = []
    for item in inbox.lines:
        if item.proposal is not None:
            out.append(item.proposal.to_line())
        else:
            out.append(item.raw)
    return "\n".join(out) + ("\n" if out else "")


def save_inbox(paths: ProjectPaths, inbox: Inbox) -> None:
    write_text(paths.inbox, dump_inbox(inbox))


def count_proposed(path: Path) -> int:
    """Count parseable lines whose status is ``proposed``. Missing file is 0.

    Lenient: a line only needs to be JSON with ``status=proposed``. Status
    (Step 2) still works on incomplete inbox fixtures.
    """
    if not path.is_file():
        return 0
    total = 0
    for raw in read_text(path).splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("status") == "proposed":
            total += 1
    return total


def next_pid_from(inboxes: Iterable[Inbox]) -> str:
    highest = 0
    for inbox in inboxes:
        for item in inbox.proposals():
            if item.id.startswith("p"):
                try:
                    highest = max(highest, int(item.id[1:]))
                except ValueError:
                    continue
    return f"p{highest + 1}"


def append_proposal(paths: ProjectPaths, proposal: Proposal) -> Proposal:
    """Assign the next p-id and append under the lock."""
    with hold_lock(paths):
        inbox = load_inbox(paths.inbox)
        archive = load_inbox(paths.inbox_archive)
        proposal.id = next_pid_from((inbox, archive))
        if not proposal.ts:
            proposal.ts = utc_now()
        if not proposal.hash:
            proposal.hash = content_hash(proposal.kind, proposal.text)
        inbox.lines.append(InboxLine(raw=proposal.to_line(), proposal=proposal))
        save_inbox(paths, inbox)
        return proposal


def rewrite_inbox(paths: ProjectPaths, inbox: Inbox) -> None:
    with hold_lock(paths):
        save_inbox(paths, inbox)


def list_proposals(
    path: Path,
    *,
    status: str = "proposed",
    kind: str | None = None,
    limit: int | None = 50,
) -> list[Proposal]:
    inbox = load_inbox(path)
    items = inbox.proposals()
    if status != "all":
        items = [item for item in items if item.status == status]
    if kind:
        items = [item for item in items if item.kind == kind]
    items.sort(key=lambda item: (item.ts, item.id))
    if limit is not None:
        items = items[:limit]
    return items
