"""Parse a fenced costanza paste block and turn it into proposals / NOW."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from costanza.config import load_config
from costanza.constants import NOW_KEYS, PASTE_MAX_BYTES, PASTE_MAX_ITEMS
from costanza.exceptions import UsageError
from costanza.format import HARD_LINE_LIMIT, forbidden_label, path_problem
from costanza.now import apply_now
from costanza.paths import ProjectPaths, discover_root
from costanza.propose import ProposeResult, propose
from costanza.text import normalise, parse_files, split_inline

OPEN_RE = re.compile(r"^(```|~~~)\s*costanza\s*$", re.IGNORECASE)
CLOSE_RE = re.compile(r"^(```|~~~)\s*$")
BULLET_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)")
ITEM_RE = re.compile(
    r"^(decide|reject|rule|gotcha|ask)\s*:\s*(.*)$",
    re.IGNORECASE,
)
NOW_RE = re.compile(
    r"^now\s+(\S+)\s*:\s*(.*)$",
    re.IGNORECASE,
)
FILES_RE = re.compile(r"\s*\[files:\s*(.*?)]\s*$", re.IGNORECASE)
SHA_RE = re.compile(r"@[0-9a-fA-F]{7,12}\b")
KIND_OF = {
    "decide": "D",
    "reject": "X",
    "rule": "R",
    "gotcha": "G",
    "ask": "Q",
}
SMART_TABLE = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00a0": " ",
        "\u202f": " ",
    }
)

_DASH_SPACED = (
    (" \u2014 ", " -- "),
    (" \u2013 ", " -- "),
    (" \u2212 ", " -- "),
)


@dataclass
class PasteItem:
    kind: str
    text: str
    why: str | None
    files: list[str]
    line: int
    now_key: str | None = None


@dataclass
class PasteIssue:
    line: int
    message: str


@dataclass
class AppliedRow:
    line: int
    result: str
    detail: str
    proposal_id: str | None = None


@dataclass
class PasteResult:
    items: list[PasteItem] = field(default_factory=list)
    issues: list[PasteIssue] = field(default_factory=list)
    applied: list[AppliedRow] = field(default_factory=list)
    now_changed: tuple[str, ...] = ()
    proposed: int = 0
    duplicates: int = 0
    wrote: bool = False
    over_budget: str | None = None


def tidy(text: str) -> str:
    """Turn messy chat punctuation into the ASCII the grammar expects."""
    text = text.replace("\x00", "")
    text = text.translate(SMART_TABLE)
    for src, dest in _DASH_SPACED:
        text = text.replace(src, dest)
    return text


def _strip_bullet(line: str) -> str:
    return BULLET_RE.sub("", line, count=1)


def _issue(line: int, message: str) -> PasteIssue:
    return PasteIssue(line=line, message=message)


def _parse_body(body: str, lineno: int) -> tuple[PasteItem | None, PasteIssue | None]:
    if SHA_RE.search(body):
        match = SHA_RE.search(body)
        sha = match.group(0) if match else "@sha"
        return None, _issue(lineno, f'commit refs are added by Costanza; remove "{sha}"')
    files: list[str] = []
    files_match = FILES_RE.search(body)
    if files_match:
        raw_files = files_match.group(1)
        body = body[: files_match.start()].rstrip()
        try:
            files = parse_files(raw_files)
        except UsageError as exc:
            first = raw_files.split(",")[0].strip() if raw_files.strip() else ""
            problem = path_problem(first) if first else "path is empty; use a repo-relative path like app/db.py"
            if problem is None:
                return None, _issue(lineno, exc.message)
            return None, _issue(lineno, f'unsafe path "{first}": {problem}')
    try:
        text, why = split_inline(body, None)
    except UsageError as exc:
        return None, _issue(lineno, exc.message)
    text = normalise(text) if text.strip() else ""
    why = normalise(why) if why and why.strip() else None
    return (
        PasteItem(kind="", text=text, why=why, files=files, line=lineno),
        None,
    )


def parse_item_line(raw: str, lineno: int) -> tuple[PasteItem | None, PasteIssue | None, bool]:
    """Parse one body line. Returns (item, issue, ignored)."""
    cleaned = tidy(raw).strip()
    if not cleaned:
        return None, None, True
    cleaned = _strip_bullet(cleaned).strip()
    if not cleaned or cleaned.startswith("#"):
        return None, None, True
    length = len(cleaned)
    if length > HARD_LINE_LIMIT:
        return None, _issue(lineno, f"line is {length} characters (max {HARD_LINE_LIMIT})"), False
    bad = forbidden_label(cleaned)
    if bad is not None:
        return None, _issue(lineno, f"forbidden character {bad}"), False

    now_match = NOW_RE.match(cleaned)
    if now_match:
        key = now_match.group(1).strip().lower()
        body = now_match.group(2)
        if key not in NOW_KEYS:
            return None, _issue(lineno, "now key must be doing, done, next or blocked"), False
        item, issue = _parse_body(body, lineno)
        if issue is not None:
            return None, issue, False
        assert item is not None
        if not item.text:
            return None, _issue(lineno, "empty text"), False
        if item.files or item.why:
            # NOW lines have no files / reason in the grammar; keep the text only.
            pass
        item.kind = "now"
        item.now_key = key
        return item, None, False

    item_match = ITEM_RE.match(cleaned)
    if item_match is None:
        token = cleaned.split(":", 1)[0].strip() or cleaned.split()[0]
        lower = token.lower()
        if lower in KIND_OF or lower == "now":
            return None, _issue(lineno, f'missing ":" after "{token}"'), False
        return None, _issue(
            lineno,
            f'unknown type "{token}" (expected decide, reject, rule, gotcha, ask, now)',
        ), False

    type_name = item_match.group(1).lower()
    body = item_match.group(2)
    item, issue = _parse_body(body, lineno)
    if issue is not None:
        return None, issue, False
    assert item is not None
    if not item.text:
        return None, _issue(lineno, "empty text"), False
    if type_name == "reject" and not item.why:
        return None, _issue(lineno, 'reject needs a reason; add " -- why"'), False
    item.kind = KIND_OF[type_name]
    return item, None, False


def extract_blocks(text: str) -> tuple[list[list[tuple[int, str]]], list[PasteIssue]]:
    """Return fenced bodies as (lineno, line) lists, plus fence issues."""
    issues: list[PasteIssue] = []
    raw_lines = text.splitlines()
    blocks: list[list[tuple[int, str]]] = []
    index = 0
    while index < len(raw_lines):
        open_match = OPEN_RE.match(raw_lines[index].rstrip())
        if open_match is None:
            index += 1
            continue
        fence = open_match.group(1)
        open_line = index + 1
        index += 1
        body: list[tuple[int, str]] = []
        closed = False
        while index < len(raw_lines):
            close_match = CLOSE_RE.match(raw_lines[index].rstrip())
            if close_match is not None and close_match.group(1) == fence:
                closed = True
                index += 1
                break
            body.append((index + 1, raw_lines[index]))
            index += 1
        if not closed:
            # Lenient: a missing closer still yields a body.
            pass
        blocks.append(body)
        _ = open_line
    return blocks, issues


def parse_paste(text: str) -> tuple[list[PasteItem], list[PasteIssue]]:
    if len(text.encode("utf-8")) > PASTE_MAX_BYTES:
        raise UsageError(
            f"paste is larger than {PASTE_MAX_BYTES} bytes",
            "trim the reply and paste again",
        )
    blocks, issues = extract_blocks(text)
    items: list[PasteItem] = []
    if not blocks:
        raw_lines = text.splitlines()
        probe: list[PasteItem] = []
        probe_issues: list[PasteIssue] = []
        for lineno, raw in enumerate(raw_lines, start=1):
            item, issue, ignored = parse_item_line(raw, lineno)
            if ignored:
                continue
            if issue is not None:
                probe_issues.append(issue)
            elif item is not None:
                probe.append(item)
        if probe and not probe_issues:
            items = probe
        else:
            issues.append(_issue(1, "no costanza block found"))
            return items, issues
    else:
        for body in blocks:
            for lineno, raw in body:
                item, issue, ignored = parse_item_line(raw, lineno)
                if ignored:
                    continue
                if issue is not None:
                    issues.append(issue)
                elif item is not None:
                    items.append(item)

    if len(items) > PASTE_MAX_ITEMS:
        issues.append(_issue(items[PASTE_MAX_ITEMS].line, "more than 200 items"))
        items = items[:PASTE_MAX_ITEMS]

    seen_now: dict[str, int] = {}
    extra: list[PasteIssue] = []
    kept: list[PasteItem] = []
    for item in items:
        if item.now_key is not None:
            previous = seen_now.get(item.now_key)
            if previous is not None:
                extra.append(_issue(item.line, f'"now {item.now_key}" appears twice'))
                continue
            seen_now[item.now_key] = item.line
        kept.append(item)
    issues.extend(extra)
    issues.sort(key=lambda item: item.line)
    return kept, issues


def apply_paste(
    text: str,
    *,
    dry_run: bool = False,
    partial: bool = False,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> PasteResult:
    items, issues = parse_paste(text)
    result = PasteResult(items=items, issues=issues)
    if issues and not partial:
        return result
    if dry_run:
        result.applied = [
            AppliedRow(line=item.line, result="parsed", detail=item.now_key or item.kind)
            for item in items
        ]
        return result
    if not items:
        return result

    root = discover_root(cwd, explicit, allow_cwd=False)
    now_kwargs: dict[str, str] = {}
    for item in items:
        if item.now_key is not None:
            now_kwargs[item.now_key] = item.text
    if now_kwargs:
        now_result = apply_now(
            doing=now_kwargs.get("doing"),
            done=now_kwargs.get("done"),
            next_items=now_kwargs.get("next"),
            blocked=now_kwargs.get("blocked"),
            cwd=cwd,
            explicit=explicit,
        )
        result.now_changed = now_result.changed
        result.wrote = True
        if now_result.write is not None:
            from costanza.tokens import active_count, bind

            config = load_config(ProjectPaths(root).config)
            bind(config.tokenizer, config.tokenizer_encoding, config.tokenizer_cache, root)
            tokens = active_count(now_result.write.text)
            if tokens > config.budget_tokens:
                if config.auto_compact:
                    from costanza.compact import compact_file

                    compact_file(apply=True, cwd=cwd, explicit=explicit)
                else:
                    result.over_budget = f"over budget ({tokens:,} / {config.budget_tokens:,})"

    for item in items:
        if item.now_key is not None:
            result.applied.append(
                AppliedRow(line=item.line, result="now", detail=item.now_key or "")
            )
            continue
        files = ",".join(item.files) if item.files else None
        proposed = propose(
            item.kind,
            item.text,
            why=item.why,
            files=files,
            source="paste",
            cwd=cwd,
            explicit=explicit,
        )
        row = _row_from_propose(item.line, proposed)
        result.applied.append(row)
        if proposed.result == "proposed":
            result.proposed += 1
            result.wrote = True
        else:
            result.duplicates += 1
    return result


def _row_from_propose(line: int, proposed: ProposeResult) -> AppliedRow:
    pid = proposed.proposal.id if proposed.proposal is not None else proposed.ref
    return AppliedRow(
        line=line,
        result=proposed.result,
        detail=pid or "",
        proposal_id=pid,
    )
