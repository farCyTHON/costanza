"""Accept, dismiss, review and resolve."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from costanza import gate
from costanza.config import load_config
from costanza.exceptions import CostanzaError, UsageError
from costanza.format import Document, Entry, length_warning, next_id, render_entry
from costanza.hooks import landing_sha
from costanza.inbox import Inbox, Proposal, load_inbox, rewrite_inbox, utc_now
from costanza.paths import ProjectPaths, discover_root
from costanza.propose import ProposeResult, preview_entry_line, propose
from costanza.scrub import redact
from costanza.store import (
    WriteResult,
    add_entry,
    append_archive,
    archive_texts,
    drop_entry,
    mutate_file,
    read_file,
)
from costanza.text import parse_files, require_clean


@dataclass
class AcceptItem:
    proposal: Proposal
    entry_id: str
    line: str


@dataclass
class AcceptResult:
    items: list[AcceptItem]
    skipped: list[str]
    write: WriteResult | None
    nothing: bool = False
    over_budget: str | None = None


def _paths(cwd: Path | None, explicit: Path | None) -> ProjectPaths:
    return ProjectPaths(discover_root(cwd, explicit, allow_cwd=False))


def _load(paths: ProjectPaths) -> Inbox:
    return load_inbox(paths.inbox)


def _require_pid(inbox: Inbox, pid: str) -> Proposal:
    item = inbox.by_id(pid)
    if item is None:
        raise CostanzaError(f"no proposal {pid}", "cz list")
    return item


def _edit_proposal(item: Proposal, text: str | None, why: str | None, files: str | None) -> None:
    if text is None and why is None and files is None:
        return
    config_allow: list[str] = []
    if text is not None:
        cleaned = require_clean(text, "text")
        item.text = redact(cleaned, config_allow).text
    if why is not None:
        cleaned = require_clean(why, "why")
        item.why = redact(cleaned, config_allow).text
    if files is not None:
        item.files = parse_files(files)
    from costanza.text import content_hash

    item.hash = content_hash(item.kind, item.text)


def _build_entry(item: Proposal, entry_id: str, *, sha: str | None) -> Entry:
    number = int(entry_id[1:])
    return Entry(
        kind=item.kind,
        number=number,
        text=item.text,
        reason=item.why,
        sha=sha,
        files=tuple(item.files),
    )


def accept_proposals(
    pids: list[str] | None,
    *,
    all_open: bool = False,
    text: str | None = None,
    why: str | None = None,
    files: str | None = None,
    via: str = "accept",
    preconfirmed: bool = False,
    suggested_only: bool = False,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> AcceptResult:
    paths = _paths(cwd, explicit)
    inbox = _load(paths)
    config = load_config(paths.config)
    from costanza.tokens import bind

    bind(config.tokenizer, config.tokenizer_encoding, config.tokenizer_cache, paths.root)
    if suggested_only:
        if pids or all_open or text is not None or why is not None or files is not None:
            raise UsageError("--suggested takes no ids or edit flags", "cz accept --suggested")
        targets = [
            item for item in inbox.proposals() if item.status == "proposed" and item.suggested
        ]
        targets.sort(key=lambda item: (item.ts, item.id))
    elif all_open:
        targets = list(inbox.proposed())
        if text is not None or why is not None or files is not None:
            raise UsageError("--text/--why/--files need exactly one PID", "pass one proposal id")
    else:
        if not pids:
            raise UsageError("pass proposal ids or --all", "cz list")
        targets = [_require_pid(inbox, pid) for pid in pids]

    skipped: list[str] = []
    pending: list[Proposal] = []
    for item in targets:
        if item.status == "accepted":
            skipped.append(f"{item.id} already accepted as {item.entry or '?'}")
            continue
        if item.status in {"rejected", "dismissed"}:
            raise CostanzaError(f"{item.id} is {item.status}", "propose it again")
        pending.append(item)

    if not pending:
        return AcceptResult(items=[], skipped=skipped, write=None, nothing=True)

    if len(pending) != 1 and (text is not None or why is not None or files is not None):
        raise UsageError("--text/--why/--files need exactly one PID", "pass one proposal id")
    if len(pending) == 1:
        _edit_proposal(pending[0], text, why, files)
        others = [item for item in inbox.proposed() if item.id != pending[0].id]
        for other in others:
            if other.hash == pending[0].hash:
                raise CostanzaError(
                    f"edit makes {pending[0].id} a duplicate of {other.id}",
                    "change the text",
                )

    previous, document = read_file(paths)
    extras = archive_texts(paths)
    planned: list[AcceptItem] = []
    working = document
    for item in pending:
        entry_id = next_id(item.kind, working, *extras)
        sha = item.commit if config.entry_sha and item.commit else None
        entry = _build_entry(item, entry_id, sha=sha)
        planned.append(AcceptItem(proposal=item, entry_id=entry_id, line=render_entry(entry)))
        working = add_entry(working, entry)
        extras = extras  # high-water also sees working via next_id(document)

    noun = "proposal" if len(planned) == 1 else "proposals"
    listing = "\n".join(f"{plan.proposal.id} → {plan.line}" for plan in planned)
    question = f"{listing}\naccept {len(planned)} {noun} into COSTANZA.md?"
    if not gate.confirm(question, preconfirmed=preconfirmed):
        return AcceptResult(items=[], skipped=skipped, write=None, nothing=True)

    def mutator(current: Document) -> Document:
        updated = current
        extra = archive_texts(paths)
        for plan in planned:
            eid = next_id(plan.proposal.kind, updated, *extra)
            sha = plan.proposal.commit if config.entry_sha and plan.proposal.commit else None
            entry = _build_entry(plan.proposal, eid, sha=sha)
            plan.entry_id = eid
            plan.line = render_entry(entry)
            updated = add_entry(updated, entry)
            if plan.proposal.resolves:
                updated, found = drop_entry(updated, plan.proposal.resolves)
                if found is not None:
                    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    heading = f"## {day} resolved {found.id}: see {eid}"
                    append_archive(paths, heading, render_entry(found))
        return updated

    write = mutate_file(
        paths, previous, mutator, ", ".join(f"{p.proposal.id} → {p.entry_id}" for p in planned)
    )
    now = utc_now()
    for plan in planned:
        plan.proposal.status = "accepted"
        plan.proposal.entry = plan.entry_id
        plan.proposal.decided = now
        plan.proposal.via = via
    rewrite_inbox(paths, inbox)
    over: str | None = None
    if write is not None:
        from costanza.tokens import active_count

        tokens = active_count(write.text)
        if tokens > config.budget_tokens:
            if config.auto_compact:
                from costanza.compact import compact_file

                compact_file(apply=True, cwd=cwd, explicit=explicit)
            else:
                over = f"over budget ({tokens:,} / {config.budget_tokens:,})"
    return AcceptResult(items=planned, skipped=skipped, write=write, over_budget=over)


def dismiss_proposals(
    pids: list[str] | None,
    *,
    reject: bool = False,
    via: str = "dismiss",
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> list[str]:
    if not pids:
        raise UsageError("pass proposal ids", "cz list")
    paths = _paths(cwd, explicit)
    inbox = _load(paths)
    messages: list[str] = []
    now = utc_now()
    for pid in pids:
        item = _require_pid(inbox, pid)
        if item.status != "proposed":
            messages.append(f"{pid} already {item.status}")
            continue
        item.status = "rejected" if reject else "dismissed"
        item.decided = now
        item.via = via
        messages.append(f"{pid} {'rejected' if reject else 'dismissed'}")
    rewrite_inbox(paths, inbox)
    return messages


@dataclass
class ReviewHooks:
    is_tty: Callable[[], bool]
    read_key: Callable[[], str]
    read_line: Callable[[str, str], str]
    confirm: Callable[[str], bool]
    show: Callable[[Proposal, int, int], None]
    ok: Callable[[str], None]
    info: Callable[[str], None]
    warn: Callable[[str], None]
    err: Callable[[str], None]


def review_loop(
    *,
    kind: str | None = None,
    hooks: ReviewHooks,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> dict[str, int]:
    if not hooks.is_tty():
        raise UsageError(
            "review needs an interactive terminal",
            "run cz review in your own terminal (cz dismiss <id> works from scripts)",
        )
    paths = _paths(cwd, explicit)
    inbox = _load(paths)
    items = inbox.proposed()
    if kind:
        from costanza.propose import parse_kind

        want = parse_kind(kind)
        items = [item for item in items if item.kind == want]
    items = sorted(items, key=lambda item: (0 if item.suggested else 1, item.ts, item.id))
    cache: dict[str, set[str] | None] = {}
    for item in items:
        landed = landing_sha(paths.root, item, cache)
        if landed:
            item.landing = landed
    counts = {"accepted": 0, "rejected": 0, "dismissed": 0, "skipped": 0}
    config = load_config(paths.config)
    index = 0
    while index < len(items):
        item = items[index]
        hooks.show(item, index, len(items))
        sha = item.commit if config.entry_sha and item.commit else None
        preview = preview_entry_line(paths, item.kind, item.text, item.why, item.files, sha=sha)
        note = length_warning(preview, review=True)
        if note:
            hooks.warn(note)
        key = hooks.read_key().strip().lower()[:1]
        if key == "a":
            result = accept_proposals(
                [item.id],
                via="review",
                preconfirmed=True,
                cwd=cwd,
                explicit=explicit,
            )
            if result.items:
                counts["accepted"] += 1
                hooks.ok(f"{item.id} → {result.items[0].entry_id}")
            elif result.nothing:
                hooks.info("nothing accepted")
            index += 1
        elif key == "r":
            # A proposed decision becomes an X entry (Step 4 prompt). Other kinds
            # are marked rejected and do not touch COSTANZA.md (spec 3.2).
            if item.kind == "D":
                from costanza.text import content_hash

                live_inbox = _load(paths)
                live = live_inbox.by_id(item.id)
                if live is not None:
                    live.kind = "X"
                    live.hash = content_hash("X", live.text)
                    if not live.why:
                        live.why = "rejected in review"
                    rewrite_inbox(paths, live_inbox)
                result = accept_proposals(
                    [item.id],
                    via="review",
                    preconfirmed=True,
                    cwd=cwd,
                    explicit=explicit,
                )
                if result.items:
                    counts["accepted"] += 1
                    hooks.ok(f"{item.id} → {result.items[0].entry_id} (rejected as X)")
                    index += 1
                    continue
            msgs = dismiss_proposals([item.id], reject=True, via="review", cwd=cwd, explicit=explicit)
            counts["rejected"] += 1
            hooks.info(msgs[0] if msgs else f"{item.id} rejected")
            index += 1
        elif key == "d":
            msgs = dismiss_proposals([item.id], reject=False, via="review", cwd=cwd, explicit=explicit)
            counts["dismissed"] += 1
            hooks.info(msgs[0] if msgs else f"{item.id} dismissed")
            index += 1
        elif key == "e":
            new_text = hooks.read_line("text", item.text)
            new_why = hooks.read_line("why", item.why or "")
            new_files = hooks.read_line("files", ", ".join(item.files))
            draft = replace(item, files=list(item.files))
            try:
                _edit_proposal(
                    draft,
                    new_text or None,
                    new_why or None,
                    new_files if new_files != ", ".join(item.files) else None,
                )
                for other in items:
                    if other.id != item.id and other.hash == draft.hash:
                        raise CostanzaError(
                            f"edit makes {item.id} a duplicate of {other.id}",
                            "change the text",
                        )
            except CostanzaError as exc:
                hooks.err(exc.message)
                continue
            shown = draft.text
            if draft.why:
                shown += f" -- {draft.why}"
            if draft.files:
                shown += f" [files: {', '.join(draft.files)}]"
            hooks.info(f"{item.id} {shown}")
            if not hooks.confirm(f"keep this edit of {item.id}?"):
                hooks.info("edit discarded")
                continue
            inbox_now = _load(paths)
            live = inbox_now.by_id(item.id)
            if live is not None:
                live.text = draft.text
                live.why = draft.why
                live.files = list(draft.files)
                live.hash = draft.hash
            rewrite_inbox(paths, inbox_now)
            item.text = draft.text
            item.why = draft.why
            item.files = list(draft.files)
            item.hash = draft.hash
        elif key == "s":
            counts["skipped"] += 1
            index += 1
        elif key == "q":
            break
        elif key == "?":
            hooks.info("[a]ccept  [r]eject  [d]ismiss  [e]dit  [s]kip  [q]uit")
        else:
            hooks.warn(f"unknown key {key!r}; press ? for help")
    return counts


def resolve_entry(
    entry_id: str,
    *,
    note: str | None = None,
    decide_text: str | None = None,
    why: str | None = None,
    files: str | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> ProposeResult | WriteResult:
    if decide_text is not None and note is not None:
        raise UsageError("use --note or --decide, not both", "cz resolve --help")
    if decide_text is None and note is None:
        raise UsageError("pass --note or --decide", "cz resolve Q1 --note \"per user\"")
    if not entry_id or entry_id[0] not in {"Q", "G"}:
        raise UsageError(f"{entry_id} is not a Q or G id", "cz resolve Q1 --note \"…\"")

    paths = _paths(cwd, explicit)
    previous, document = read_file(paths)
    found = next((item for item in document.all_entries() if item.id == entry_id), None)
    if found is None or found.kind not in {"Q", "G"}:
        raise UsageError(f"{entry_id} is not a Q or G entry in COSTANZA.md", "cz status")

    if decide_text is not None:
        return propose(
            "D",
            decide_text,
            why=why,
            files=files,
            resolves=entry_id,
            cwd=cwd,
            explicit=explicit,
        )

    if not gate.confirm(f"archive {entry_id} out of COSTANZA.md?"):
        return ProposeResult(result="nothing")

    def mutator(current: Document) -> Document:
        updated, removed = drop_entry(current, entry_id)
        if removed is not None:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            heading = f"## {day} resolved {entry_id}: {note}"
            append_archive(paths, heading, render_entry(removed))
        return updated

    return mutate_file(paths, previous, mutator, f"resolved {entry_id}")
