"""Move overflow entries to the archive, or old inbox lines to the inbox archive."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from costanza import gate
from costanza.config import Config, load_config
from costanza.exceptions import UsageError
from costanza.format import Document, Entry, render, render_entry
from costanza.inbox import Inbox, InboxLine, Proposal, dump_inbox, load_inbox, save_inbox
from costanza.io import write_text
from costanza.lock import hold_lock
from costanza.paths import ProjectPaths, discover_root
from costanza.store import (
    append_archive_lines,
    drop_entry,
    mutate_file,
    read_file,
    set_header_extra,
)
from costanza.tokens import active_count, bind


@dataclass
class CompactResult:
    moved: list[str]
    archive: str | None
    tokens_before: int
    tokens_after: int
    target: int
    applied: bool
    still_over: list[tuple[str, int]]
    nothing: bool = False
    inbox: bool = False
    purged: int = 0
    kept_proposed: int = 0
    kept_unreadable: int = 0
    status_counts: dict[str, int] | None = None
    budget: int = 1800
    compact_ratio: float = 0.85


def compact_order(document: Document) -> list[Entry]:
    """Spec 2.4 order. Within a tier, ascending ID number."""
    tiers = (
        [item for item in document.gotchas if not item.files],
        [item for item in document.decisions if not item.files],
        list(document.rejected),
        [item for item in document.gotchas if item.files],
        [item for item in document.decisions if item.files],
    )
    ordered: list[Entry] = []
    for group in tiers:
        ordered.extend(sorted(group, key=lambda item: item.number))
    return ordered


def _block_tokens(heading: str, lines: list[str]) -> int:
    return active_count("\n".join([heading, *lines]) + "\n")


def _section_tokens(document: Document) -> list[tuple[str, int]]:
    now = (
        f"## NOW\ndoing: {document.now.doing}\ndone: {document.now.done}\n"
        f"next: {document.now.next}\nblocked: {document.now.blocked}\n"
    )
    rows = [
        ("NOW", active_count(now)),
        ("RULES", _block_tokens("## RULES", [render_entry(item) for item in document.rules])),
        ("OPEN", _block_tokens("## OPEN", [render_entry(item) for item in document.open])),
        (
            "DECISIONS",
            _block_tokens("## DECISIONS", [render_entry(item) for item in document.decisions]),
        ),
        (
            "REJECTED",
            _block_tokens("## REJECTED", [render_entry(item) for item in document.rejected]),
        ),
        ("GOTCHAS", _block_tokens("## GOTCHAS", [render_entry(item) for item in document.gotchas])),
    ]
    rows.sort(key=lambda item: item[1], reverse=True)
    return [(name, tokens) for name, tokens in rows if tokens]


def _without(document: Document, entry_id: str) -> Document:
    updated, _found = drop_entry(document, entry_id)
    return updated


def _pointer(document: Document, rel: str) -> Document:
    return replace(document, header=set_header_extra(document.header, "archive", rel))


def plan_file_moves(document: Document, target: int) -> tuple[list[Entry], Document]:
    working = document
    moved: list[Entry] = []
    if active_count(render(working)) <= target:
        return moved, working
    for entry in compact_order(document):
        if active_count(render(working)) <= target:
            break
        working = _without(working, entry.id)
        moved.append(entry)
    return moved, working


def compact_file(
    *,
    apply: bool,
    target: int | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> tuple[CompactResult, Config]:
    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    bind(config.tokenizer, config.tokenizer_encoding, config.tokenizer_cache, root)
    ceiling = target if target is not None else int(config.budget_tokens * config.compact_target)
    previous, document = read_file(paths)
    before = active_count(previous if previous.endswith("\n") else previous + "\n")
    # active_count() already treats the file as written; re-render for a stable before.
    before = active_count(render(document))
    moved, reduced = plan_file_moves(document, ceiling)
    still: list[tuple[str, int]] = []
    if not moved:
        still = _section_tokens(document) if before > config.budget_tokens else []
        return (
            CompactResult(
                moved=[],
                archive=None,
                tokens_before=before,
                tokens_after=before,
                target=ceiling,
                applied=apply,
                still_over=still,
                nothing=not still,
                budget=config.budget_tokens,
                compact_ratio=config.compact_target,
            ),
            config,
        )

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    rel = f".costanza/archive/{month}.md"
    planned = _pointer(reduced, rel)
    after = active_count(render(planned))
    if after > config.budget_tokens:
        still = _section_tokens(planned)

    if apply:
        heading = f"## {day} compact"

        def mutator(current: Document) -> Document:
            live_moved, live_reduced = plan_file_moves(current, ceiling)
            append_archive_lines(paths, heading, [render_entry(item) for item in live_moved])
            return _pointer(live_reduced, rel)

        mutate_file(paths, previous, mutator, f"compact {', '.join(item.id for item in moved)}")
        after = active_count(read_file(paths)[0])
        if after > config.budget_tokens:
            still = _section_tokens(read_file(paths)[1])

    return (
        CompactResult(
            moved=[item.id for item in moved],
            archive=rel,
            tokens_before=before,
            tokens_after=after,
            target=ceiling,
            applied=apply,
            still_over=still,
            nothing=False,
            budget=config.budget_tokens,
            compact_ratio=config.compact_target,
        ),
        config,
    )


def _age_days(value: str | None) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def _eligible(item: Proposal, days: int) -> bool:
    if item.status not in {"accepted", "rejected", "dismissed"}:
        return False
    age = _age_days(item.decided)
    return age is not None and age >= days


def _tombstone(item: Proposal) -> Proposal:
    return Proposal(
        id=item.id,
        kind=item.kind,
        text="",
        status=item.status,
        hash=item.hash,
        decided=item.decided,
        purged=True,
        extra={},
    )


def compact_inbox(
    *,
    apply: bool,
    purge: bool = False,
    older_than: int | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> tuple[CompactResult, Config]:
    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    bind(config.tokenizer, config.tokenizer_encoding, config.tokenizer_cache, root)
    days = older_than if older_than is not None else (config.purge_days if purge else config.retain_days)
    inbox = load_inbox(paths.inbox)
    archive = load_inbox(paths.inbox_archive)
    if purge:
        eligible = [item for item in archive.proposals() if _eligible(item, days) and not item.purged]
        counts = {status: 0 for status in ("accepted", "rejected", "dismissed")}
        for item in eligible:
            counts[item.status] = counts.get(item.status, 0) + 1
        if apply and eligible:
            if not gate.confirm(f"permanently erase the text of {len(eligible)} decided proposals?"):
                return (
                    CompactResult(
                        moved=[],
                        archive=".costanza/inbox-archive.jsonl",
                        tokens_before=0,
                        tokens_after=0,
                        target=days,
                        applied=False,
                        still_over=[],
                        inbox=True,
                        purged=0,
                    ),
                    config,
                )
            with hold_lock(paths):
                live = load_inbox(paths.inbox_archive)
                new_lines: list[InboxLine] = []
                for line in live.lines:
                    if line.proposal is not None and _eligible(line.proposal, days) and not line.proposal.purged:
                        stone = _tombstone(line.proposal)
                        new_lines.append(InboxLine(raw=stone.to_line(), proposal=stone))
                    else:
                        new_lines.append(line)
                write_text(paths.inbox_archive, dump_inbox(Inbox(lines=new_lines)))
        return (
            CompactResult(
                moved=[item.id for item in eligible],
                archive=".costanza/inbox-archive.jsonl",
                tokens_before=0,
                tokens_after=0,
                target=days,
                applied=apply,
                still_over=[],
                inbox=True,
                purged=len(eligible) if apply else 0,
                status_counts=counts,
            ),
            config,
        )

    eligible_lines = [
        line
        for line in inbox.lines
        if line.proposal is not None and _eligible(line.proposal, days)
    ]
    keep = [line for line in inbox.lines if line not in eligible_lines]
    counts = {status: 0 for status in ("accepted", "rejected", "dismissed")}
    for line in eligible_lines:
        assert line.proposal is not None
        counts[line.proposal.status] = counts.get(line.proposal.status, 0) + 1
    proposed = sum(1 for line in keep if line.proposal is not None and line.proposal.status == "proposed")
    unreadable = sum(1 for line in keep if line.proposal is None)
    if apply and eligible_lines:
        with hold_lock(paths):
            live_inbox = load_inbox(paths.inbox)
            live_archive = load_inbox(paths.inbox_archive)
            moving = [
                line
                for line in live_inbox.lines
                if line.proposal is not None and _eligible(line.proposal, days)
            ]
            staying = [line for line in live_inbox.lines if line not in moving]
            live_archive.lines.extend(moving)
            write_text(paths.inbox_archive, dump_inbox(live_archive))
            save_inbox(paths, Inbox(lines=staying))
    return (
        CompactResult(
            moved=[line.proposal.id for line in eligible_lines if line.proposal is not None],
            archive=".costanza/inbox-archive.jsonl",
            tokens_before=0,
            tokens_after=0,
            target=days,
            applied=apply,
            still_over=[],
            nothing=not eligible_lines,
            inbox=True,
            kept_proposed=proposed,
            kept_unreadable=unreadable,
            status_counts=counts,
        ),
        config,
    )


def run_compact(
    *,
    apply: bool,
    dry_run: bool,
    target: int | None,
    inbox: bool,
    purge: bool,
    older_than: int | None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> tuple[CompactResult, Config]:
    if dry_run and apply:
        raise UsageError("use --apply or --dry-run, not both", "cz compact --help")
    if not inbox and (purge or older_than is not None):
        raise UsageError("--purge and --older-than need --inbox", "cz compact --inbox --help")
    if inbox and target is not None:
        raise UsageError("--target cannot be combined with --inbox", "cz compact --help")
    will_apply = apply and not dry_run
    if inbox:
        return compact_inbox(
            apply=will_apply,
            purge=purge,
            older_than=older_than,
            cwd=cwd,
            explicit=explicit,
        )
    return compact_file(apply=will_apply, target=target, cwd=cwd, explicit=explicit)
