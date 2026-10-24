"""Terminal visual language. The only module that prints."""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from typing import TextIO

from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.style import Style
from rich.text import Text
from rich.theme import Theme

from costanza.check import CheckReport
from costanza.constants import KINDS, NOW_KEYS, WIDTH
from costanza.init import InitResult
from costanza.status import StatusView

NARROW = 70
MIN_WIDTH = 40

THEME = Theme(
    {
        "cz.accent": "cyan",
        "cz.ok": "green",
        "cz.warn": "yellow",
        "cz.err": "red",
        "cz.dim": "dim",
        "cz.key": "bold",
    }
)

_SYMBOLS = {
    "ok": ("✓", "+"),
    "warn": ("!", "!"),
    "error": ("✗", "x"),
    "info": ("·", "-"),
    "arrow": ("→", "->"),
    "sep": ("·", "-"),
    "bar_full": ("█", "#"),
    "bar_empty": ("░", "."),
    "prompt": ("›", ">"),
    "ellipsis": ("…", "..."),
}


@dataclass
class _State:
    quiet: bool = False
    no_color: bool = False
    ascii: bool = False
    color_policy: str = "auto"


_state = _State()
_out: Console | None = None
_err: Console | None = None


def _env_no_color() -> bool:
    return bool(os.environ.get("NO_COLOR"))


def _detect_ascii() -> bool:
    if os.environ.get("COSTANZA_ASCII") == "1":
        return True
    if os.environ.get("COSTANZA_ASCII") == "0":
        return False
    encoding = sys.stdout.encoding or "utf-8"
    try:
        "✓█░→…".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return True
    return False


def configure(
    *,
    no_color: bool | None = None,
    quiet: bool = False,
    color_policy: str = "auto",
    ascii_policy: str = "auto",
) -> None:
    """Rebuild consoles from flags, config and environment."""
    env_off = _env_no_color()
    flag_off = bool(no_color)
    if flag_off or env_off or color_policy == "never":
        color_off = True
    elif color_policy == "always":
        color_off = False
    else:
        color_off = not sys.stdout.isatty()

    if os.environ.get("COSTANZA_ASCII") == "1" or ascii_policy == "always":
        ascii_on = True
    elif ascii_policy == "never" and os.environ.get("COSTANZA_ASCII") != "1":
        ascii_on = False
    else:
        ascii_on = _detect_ascii()

    _state.quiet = quiet
    _state.no_color = color_off
    _state.ascii = ascii_on
    _state.color_policy = color_policy
    global _out, _err
    _out = _make_console(sys.stdout)
    _err = _make_console(sys.stderr)


def display_width() -> int:
    raw = os.environ.get("COLUMNS")
    if raw is not None and raw.strip().isdigit():
        return max(MIN_WIDTH, int(raw.strip()))
    try:
        return max(MIN_WIDTH, os.get_terminal_size().columns)
    except OSError:
        return WIDTH


def _make_console(stream: TextIO) -> Console:
    return Console(
        file=stream,
        theme=THEME,
        no_color=_state.no_color,
        highlight=False,
        emoji=False,
        width=display_width(),
        legacy_windows=False,
        color_system=None if _state.no_color else "standard",
    )


def _console(err: bool = False) -> Console:
    if _out is None or _err is None:
        configure()
    assert _out is not None and _err is not None
    return _err if err else _out


def symbol(name: str) -> str:
    uni, asc = _SYMBOLS[name]
    return asc if _state.ascii else uni


def ellipsis() -> str:
    return symbol("ellipsis")


def commify(number: int) -> str:
    return f"{number:,}"


def _keep_together(text: str, index: int) -> bool:
    """True if a break between ``index-1`` and ``index`` would split a word or number."""
    if index <= 0 or index >= len(text):
        return False
    left, right = text[index - 1], text[index]
    if (left.isalnum() or left == "_") and (right.isalnum() or right == "_"):
        return True
    if left.isdigit() and right == "," and index + 1 < len(text) and text[index + 1].isdigit():
        return True
    if left == "," and right.isdigit() and index >= 2 and text[index - 2].isdigit():
        return True
    if left in "~" and right.isdigit():
        return True
    if left.isdigit() and right == "%":
        return True
    pathish = "._-"
    if left in "/\\" and (right.isalnum() or right in pathish):
        return True
    if right in "/\\" and (left.isalnum() or left in pathish):
        return True
    if left in ".-" and right.isalnum() and index >= 2 and (text[index - 2].isalnum() or text[index - 2] in "/\\"):
        return True
    if right in ".-" and left.isalnum() and index + 1 < len(text) and (
        text[index + 1].isalnum() or text[index + 1] in "/\\"
    ):
        return True
    if left.isalpha() and right == ":" and index + 1 < len(text) and text[index + 1] in "/\\":
        return True
    if left == ":" and right in "/\\" and index >= 2 and text[index - 2].isalpha():
        return True
    return False


def _cut_at_boundary(text: str, budget: int, *, allow_overflow: bool = False) -> int:
    if budget >= len(text):
        return len(text)
    cut = max(1, budget)
    while cut > 0 and _keep_together(text, cut):
        cut -= 1
    while cut > 0 and not text[cut - 1].isspace() and _keep_together(text, cut):
        cut -= 1
    while cut > 0 and not text[cut - 1].isspace() and text[cut - 1].isalnum():
        cut -= 1
    if cut <= 0:
        return len(text) if allow_overflow else budget
    return cut


def fit(text: str, width: int) -> str:
    if width <= 0:
        return ""
    mark = ellipsis()
    if len(text) <= width:
        return text
    if width <= len(mark):
        return mark[:width]
    budget = width - len(mark)
    cut = _cut_at_boundary(text, budget)
    piece = text[:cut].rstrip()
    if not piece:
        piece = text[:budget]
    return piece + mark


def wrap_hang(text: str, width: int, hang: int = 0) -> list[str]:
    """Wrap on word/number boundaries. Later lines start with ``hang`` spaces."""
    if width <= 0:
        return [""]
    first = max(1, width)
    later = max(1, width - hang)
    pad = " " * min(hang, max(0, width - 1))
    lines: list[str] = []
    remaining = text
    limit = first
    prefix = ""
    while remaining:
        if len(prefix) + len(remaining) <= (first if prefix == "" else later + hang):
            lines.append(prefix + remaining)
            break
        room = limit if prefix == "" else later
        if len(remaining) <= room:
            lines.append(prefix + remaining)
            break
        cut = _cut_at_boundary(remaining, room, allow_overflow=True)
        piece = remaining[:cut].rstrip()
        if not piece:
            piece = remaining
            cut = len(remaining)
        lines.append(prefix + piece)
        remaining = remaining[cut:].lstrip()
        prefix = pad
    return lines or [""]


def header(title: str, right: str | None = None) -> str:
    width = display_width()
    if not right:
        return fit(title, width)
    if width < NARROW:
        return fit(title, width)
    gap = 2
    room = width - len(right) - gap
    left = fit(title, max(room, 0))
    spaces = max(width - len(left) - len(right), gap)
    return f"{left}{' ' * spaces}{right}"


def header_lines(title: str, right: str | None = None) -> list[str]:
    width = display_width()
    if right and width < NARROW:
        return [fit(title, width), fit(right, width)]
    return [header(title, right)]


def kv(rows: list[tuple[str, str]], *, indent: int = 2, wrap: bool = False) -> list[str]:
    if not rows:
        return []
    width = display_width()
    key_width = max(len(key) for key, _ in rows)
    pad = " " * indent
    out: list[str] = []
    prefix_len = indent + key_width + 2
    value_width = max(1, width - prefix_len)
    for key, value in rows:
        prefix = f"{pad}{key.ljust(key_width)}  "
        if wrap:
            chunks = wrap_hang(value, value_width, hang=0)
            out.append(prefix + chunks[0])
            hang = " " * len(prefix)
            out.extend(hang + extra for extra in chunks[1:])
        else:
            out.append(prefix + fit(value, value_width))
    return out


def token_bar(tokens: int, budget: int, warn_at: float) -> str:
    filled = 0 if budget <= 0 else round(20 * min(tokens / budget, 1))
    filled = max(0, min(20, filled))
    bar = symbol("bar_full") * filled + symbol("bar_empty") * (20 - filled)
    percent = 0 if budget <= 0 else round(100 * tokens / budget)
    stats = f"~{commify(tokens)} / {commify(budget)}  {percent}%"
    label = "tokens   "
    width = display_width()
    line = f"{label}{bar}  {stats}"
    if len(line) <= width:
        return line
    avail = width - len(label) - 2 - len(stats)
    if avail >= 4:
        filled = 0 if budget <= 0 else round(avail * min(tokens / budget, 1))
        filled = max(0, min(avail, filled))
        bar = symbol("bar_full") * filled + symbol("bar_empty") * (avail - filled)
        return f"{label}{bar}  {stats}"
    return f"{label}{stats}"


def _emit(text: str, *, err: bool = False, style: str | None = None) -> None:
    console = _console(err)
    console.print(escape(text), style=style, overflow="ignore", crop=False, highlight=False)


def _emit_wrap(text: str, *, err: bool = False, style: str | None = None, hang: int = 2) -> None:
    for line in wrap_hang(text, display_width(), hang=hang):
        _emit(line, err=err, style=style)


def _emit_plain(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.write(text if text.endswith("\n") else text + "\n")
    stream.flush()


def ok(msg: str) -> None:
    if _state.quiet:
        return
    _emit_wrap(f"{symbol('ok')} {msg}", style="cz.ok")


def warn(msg: str) -> None:
    _emit_wrap(f"{symbol('warn')} {msg}", err=True, style="cz.warn")


def err(msg: str) -> None:
    _emit_wrap(f"{symbol('error')} {msg}", err=True, style="cz.err")


def info(msg: str) -> None:
    if _state.quiet:
        return
    _emit_wrap(f"{symbol('info')} {msg}", style="cz.dim")


def next_hint(text: str) -> None:
    if _state.quiet:
        return
    _emit_wrap(f"next: {text}", style="cz.accent")


def debug_traceback(exc: BaseException | None = None) -> None:
    if exc is None:
        traceback.print_exc(file=sys.stderr)
        return
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


def write_line(text: str, *, err: bool = False) -> None:
    _emit_plain(text, err=err)


def write_raw(text: str) -> None:
    """Write payload text to stdout with no styling."""
    stream = sys.stdout
    stream.write(text if text.endswith("\n") else text + "\n")
    stream.flush()


def write_json(data: object) -> None:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    _emit_plain(payload)


def deferred(command: str, step: int) -> None:
    _emit_plain(f"cz {command} arrives in Step {step}.", err=True)


def error_panel(message: str, hint: str) -> None:
    body = f"{escape(message)}\nnext: {escape(hint)}"
    box_type = box.ASCII if _state.ascii else box.ROUNDED
    panel = Panel(
        body,
        title="error",
        border_style="cz.err",
        box=box_type,
        width=display_width(),
    )
    _console(True).print(panel)


def render_init(result: InitResult) -> None:
    if _state.quiet:
        return
    ok(f"costanza initialized in {result.root}")
    for action in result.actions:
        extra = f"  {action.extra}" if action.extra else ""
        _emit(f"  {action.verb:<8} {action.path:<24}{extra}", style="cz.dim")
    next_hint("edit the header in COSTANZA.md, then cz status")


def render_status(view: StatusView) -> None:
    if _state.quiet:
        _emit_plain(
            f"{view.short_name}  {commify(view.tokens)}/{commify(view.budget)} "
            f"({view.percent}%)  {view.proposed} proposed"
        )
        return

    sep = symbol("sep")
    title = f"costanza {sep} {view.project}" if view.project else "costanza"
    if view.synced_sha and view.synced_date:
        right = f"synced {view.synced_sha} {view.synced_date}"
        if view.behind is not None:
            sep = symbol("sep")
            right = f"{right} {sep} {view.behind} behind"
    elif not view.git_repo:
        right = "no git"
    else:
        right = "synced never"
    for line in header_lines(title, right):
        _emit(line, style="cz.accent")

    bar = token_bar(view.tokens, view.budget, 0.90)
    bar_style = {"ok": "cz.accent", "warn": "cz.warn", "over": "cz.err"}[view.state]
    _emit(bar, style=bar_style)

    counts = "  ".join(f"{kind} {view.counts.get(kind, 0)}" for kind in KINDS)
    inbox = f"inbox  {view.proposed} proposed"
    for line in header_lines(f"entries  {counts}", inbox):
        _emit(line)
    _emit("NOW", style="cz.key")
    for line in kv([(key, view.now.get(key, "none")) for key in NOW_KEYS]):
        _emit(line)

    if view.problems:
        n = len(view.problems)
        noun = "problem" if n == 1 else "problems"
        warn(f"{n} {noun}; next: cz check")
    elif view.state == "warn":
        warn(
            f"near budget ({view.percent}%); "
            "cz compact will move the oldest gotchas first"
        )
    elif view.state == "over":
        warn(f"over budget ({commify(view.tokens)} / {commify(view.budget)}); next: cz compact")

    if view.next_hint and not view.problems:
        next_hint(view.next_hint)


def render_check(report: CheckReport) -> None:
    """Print format-only check findings. Each error names the line and the fix."""
    sep = symbol("sep")
    if not report.findings:
        if _state.quiet:
            _emit_plain("ok")
            return
        ok(
            f"check {sep} COSTANZA.md is valid {sep} "
            f"~{commify(report.tokens)} / {commify(report.budget)} {sep} 0 warnings"
        )
        return

    if not _state.quiet:
        for line in header_lines(
            f"check {sep} COSTANZA.md",
            f"~{commify(report.tokens)} / {commify(report.budget)}",
        ):
            _emit(line, style="cz.accent")
    for item in report.findings:
        fn = err if item.severity == "error" else warn
        fn(f"{item.code}  {item.message}")
    errors = len(report.errors)
    warnings = len(report.warnings)
    err_word = "error" if errors == 1 else "errors"
    warn_word = "warning" if warnings == 1 else "warnings"
    if not _state.quiet:
        info(f"{errors} {err_word}, {warnings} {warn_word}")
        if report.errors:
            first = report.errors[0]
            next_hint(first.hint or f"fix {first.message}, then cz check")
        else:
            first = report.warnings[0]
            next_hint(first.hint or "optional: tidy the warnings, then cz check")


def stdout_encoding() -> str:
    """Encoding of stdout, or an empty string when Python does not know it."""
    return sys.stdout.encoding or ""


def is_tty() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def ask_yes_no(message: str) -> bool:
    from costanza.exceptions import UsageError

    if not is_tty():
        raise UsageError(
            "accept needs a person at an interactive terminal",
            "run cz review in your own terminal",
        )
    stream = sys.stdout
    stream.write(f"{message} [y/N] ")
    stream.flush()
    answer = sys.stdin.readline()
    if not answer:
        return False
    return answer.strip().lower() in {"y", "yes"}


def ask_agents_mode() -> str:
    """Ask auto/all/none. Non-interactive callers get auto."""
    if not is_tty():
        return "auto"
    stream = sys.stdout
    stream.write("install agent instructions? [auto/all/none] ")
    stream.flush()
    answer = sys.stdin.readline()
    if not answer:
        return "auto"
    key = answer.strip().lower()
    if key in {"auto", "all", "none"}:
        return key
    return "auto"


def read_key() -> str:
    prompt = f"[a]ccept  [r]eject  [d]ismiss  [e]dit  [s]kip  [q]uit  {symbol('prompt')} "
    _emit(prompt, style="cz.dim")
    line = sys.stdin.readline()
    return line.strip()[:1] if line else "q"


def read_line(label: str, default: str) -> str:
    prompt = f"  {label} [{default}]: "
    for line in wrap_hang(prompt, display_width(), hang=2):
        _emit(line, style="cz.dim")
    line = sys.stdin.readline()
    if not line or not line.strip():
        return default
    return line.strip()


def render_propose(result: object) -> None:
    from costanza.propose import ProposeResult

    assert isinstance(result, ProposeResult)
    if result.result == "duplicate":
        info(f"duplicate of {result.ref}")
        return
    if result.result == "previously_rejected":
        info(f"previously rejected ({result.ref}); use --force to propose anyway")
        return
    if result.result == "already_present":
        info(f"already in COSTANZA.md as {result.ref}")
        return
    if result.result == "already_archived":
        info(f"already archived as {result.ref}")
        return
    if result.proposal is None:
        return
    item = result.proposal
    ok(f"{item.id} proposed  {item.kind}  {item.text}")
    if result.redacted:
        warn(f"redacted {len(result.redacted)} secret in {item.id} ({', '.join(result.redacted)})")
    for hit in result.near:
        extra = " (looks like a rejected idea)" if hit.kind == "X" and item.kind == "D" else ""
        warn(f"close to {hit.ref}{extra}")
    for warning in result.warnings:
        warn(warning)
    next_hint("cz review")


def render_list(rows: list[object], purged_note: bool = False) -> None:
    from costanza.inbox import Proposal

    if not rows:
        info("no proposals")
        return
    for raw in rows:
        assert isinstance(raw, Proposal)
        when = raw.ts[:10] if raw.ts else ""
        who = raw.agent or raw.source
        via = f"{who} via {raw.source}" if raw.agent else raw.source
        if raw.purged:
            _emit(f"{raw.id}  {raw.kind}  {raw.status}  (purged)")
            continue
        text = fit(raw.text, 40)
        _emit(f"{raw.id}  {raw.kind}  {raw.status}  {via}  {when}  {text}")


def render_review_card(item: object, index: int, total: int) -> None:
    from costanza.inbox import Proposal

    assert isinstance(item, Proposal)
    sep = symbol("sep")
    for line in header_lines(f"review {sep} {total} proposed", f"{index + 1} of {total}"):
        _emit(line, style="cz.accent")
    extra = f"suggested by {item.suggested}" if item.suggested else f"{item.source} {sep} {item.ts[:16]}"
    who = item.agent or item.source
    _emit(f"{item.id}  {item.kind}  {who} via {item.source} {sep} {item.ts[:16]}")
    if item.suggested:
        info(extra)
    if item.landing:
        info(f"changed in {item.landing}")
    empty = "-" if _state.ascii else "—"
    for line in kv(
        [
            ("text", item.text),
            ("why", item.why or empty),
            ("files", ", ".join(item.files) or empty),
        ],
        wrap=True,
    ):
        _emit(line)


def render_now(result: object, *, json_out: bool = False) -> None:
    from costanza.now import NowResult

    assert isinstance(result, NowResult)
    if json_out:
        write_json(result.to_json())
        return
    changed = set(result.changed)
    for key in ("doing", "done", "next", "blocked"):
        value = getattr(result.now, key)
        mark = " " if key not in changed else symbol("ok")
        _emit(f"{mark} {key}: {value}", style="cz.accent" if key in changed else None)
    if result.write is not None:
        extra = "; merged with your edits" if result.merged else ""
        ok(f"COSTANZA.md: updated NOW ({', '.join(result.changed)}){extra}")
    if result.redacted:
        warn(f"redacted {len(result.redacted)} secret in NOW ({', '.join(result.redacted)})")
    for warning in result.warnings:
        warn(warning)


def render_accept(result: object) -> None:
    from costanza.accept import AcceptResult

    assert isinstance(result, AcceptResult)
    if result.nothing and not result.items:
        for line in result.skipped:
            info(line)
        if not result.skipped:
            info("nothing accepted")
        return
    for line in result.skipped:
        info(line)
    for item in result.items:
        ok(f"{item.proposal.id} → {item.entry_id}")
    if result.write is not None:
        extra = "; merged with your edits" if result.write.merged else ""
        info(f"COSTANZA.md: {result.write.change}{extra}")
    if result.over_budget:
        warn(f"{result.over_budget}; next: cz compact")


def render_scan(result: object) -> None:
    from costanza.scan import ScanResult

    assert isinstance(result, ScanResult)
    if not result.changes:
        info("header already matches the repo")
        return
    for item in result.changes:
        verb = "wrote" if result.wrote else "would write"
        _emit(f"{item.key}: {item.old} {symbol('arrow')} {item.new}", style="cz.accent")
        info(f"{verb} {item.key}")
    if result.redacted:
        warn(f"redacted {len(result.redacted)} secret in header ({', '.join(result.redacted)})")
    if not result.wrote:
        next_hint("cz scan --write")


def _compact_nothing(result: object) -> str:
    from costanza.compact import CompactResult

    assert isinstance(result, CompactResult)
    percent = round(100 * result.compact_ratio)
    return (
        f"nothing to compact ({commify(result.tokens_before)} / {commify(result.budget)}; "
        f"target {commify(result.target)} = {percent}% of {commify(result.budget)})"
    )


def render_compact(result: object) -> None:
    from costanza.compact import CompactResult

    assert isinstance(result, CompactResult)
    if result.inbox and result.purged:
        ok(f"purged {result.purged} (tombstones kept)")
        return
    if result.inbox:
        if result.nothing:
            info("nothing to compact in the inbox")
            return
        counts = result.status_counts or {}
        if not result.applied:
            info(
                f"would move {len(result.moved)} (accepted {counts.get('accepted', 0)}, "
                f"rejected {counts.get('rejected', 0)}, dismissed {counts.get('dismissed', 0)}); "
                f"keeps {result.kept_proposed} proposed, {result.kept_unreadable} unreadable"
            )
            next_hint("cz compact --inbox --apply")
            return
        ok(f"moved {len(result.moved)} decided proposals → {result.archive}")
        return
    if result.nothing and not result.still_over:
        info(_compact_nothing(result))
        return
    if result.still_over and not result.moved:
        parts = ", ".join(f"{name} {tokens}" for name, tokens in result.still_over)
        err(f"still over budget: {parts} tokens")
        return
    ids = " ".join(result.moved)
    arrow = symbol("arrow")
    sep = symbol("sep")
    verb = "moved" if result.applied else "would move"
    dest = result.archive or ".costanza/archive/"
    ok(
        f"{verb} {len(result.moved)} entries ({ids}) {arrow} {dest} {sep} "
        f"{commify(result.tokens_before)} {arrow} {commify(result.tokens_after)} tokens"
    )
    if result.still_over:
        parts = ", ".join(f"{name} {tokens}" for name, tokens in result.still_over)
        err(f"still over budget: {parts} tokens")
    if not result.applied:
        next_hint("cz compact --apply")


def render_sync(result: object) -> None:
    from costanza.sync import SyncResult

    assert isinstance(result, SyncResult)
    for notice in result.notices:
        warn(notice.message)
    if result.skipped_history:
        info("previous synced commit is not in history; skipped the change list")
    if result.applied:
        ok(f"synced {result.sha} {result.date}")
    else:
        info(f"would set synced: {result.sha} {result.date}")
        next_hint("cz sync")


def render_review_done(counts: dict[str, int]) -> None:
    sep = symbol("sep")
    info(
        f"done {sep} accepted {counts['accepted']} {sep} rejected {counts['rejected']} "
        f"{sep} dismissed {counts['dismissed']} {sep} skipped {counts['skipped']}"
    )


def render_paste(result: object, *, dry_run: bool = False) -> None:
    from costanza.paste import PasteResult

    assert isinstance(result, PasteResult)
    if result.issues:
        n = len(result.issues)
        noun = "line" if n == 1 else "lines"
        if result.wrote:
            err(f"paste: {n} {noun} need fixing; good lines were applied")
        else:
            err(f"paste: {n} {noun} need fixing; nothing was written")
        for issue in result.issues:
            _emit(f"  line {issue.line}: {issue.message}", err=True)
        next_hint("fix the lines and paste again, or cz paste --partial to apply the rest")
        if not result.wrote:
            return
    for row in result.applied:
        if row.result == "proposed":
            ok(f"{row.proposal_id or 'item'} proposed")
        elif row.result == "now":
            ok(f"NOW {row.detail}")
        elif row.result == "parsed":
            info(f"line {row.line} {row.detail}")
        elif row.result == "duplicate":
            info(f"duplicate of {row.detail}")
        else:
            info(f"{row.result} {row.detail}".strip())
    bits: list[str] = []
    if dry_run:
        bits.append("dry-run")
    if result.proposed:
        bits.append(f"{result.proposed} proposed")
    if result.duplicates:
        bits.append(f"{result.duplicates} duplicate")
    if result.now_changed:
        bits.append("NOW updated (" + ", ".join(result.now_changed) + ")")
    if bits:
        ok(", ".join(bits))
    elif not result.issues:
        info("nothing to apply")
    if result.over_budget:
        warn(f"{result.over_budget}; next: cz compact")


def render_agents(result: object) -> None:
    from costanza.agents import AgentsResult

    assert isinstance(result, AgentsResult)
    for row in result.rows:
        extra = f"  {row.detail}" if row.detail else ""
        message = f"{row.path}  {row.status}{extra}"
        if row.status in {"failed", "newer"}:
            err(message)
        elif row.status in {"unchanged", "missing"}:
            info(message)
        else:
            ok(message)


def render_handoff(result: object, *, copied: object | None) -> None:
    from costanza.clipboard import CopyResult
    from costanza.handoff import HandoffResult

    assert isinstance(result, HandoffResult)
    if _state.quiet:
        return
    sep = symbol("sep")
    tokens = commify(result.tokens)
    if copied is None:
        extra = f"(file {commify(result.file_tokens)} + instructions {commify(result.instruction_tokens)})"
        line = f"{symbol('ok')} handoff {sep} ~{tokens} tokens {extra}"
    else:
        assert isinstance(copied, CopyResult)
        if copied.verified:
            state = "copied to clipboard (verified)"
        else:
            state = "copied to clipboard (not verified)"
        line = f"{symbol('ok')} handoff {sep} ~{tokens} tokens {sep} {state}"
    _emit_wrap(line, err=True, style="cz.ok")


def render_doctor(result: object) -> None:
    """One row per check, then next: for the first failure."""
    from costanza.doctor import DoctorReport

    assert isinstance(result, DoctorReport)
    printers = {"ok": ok, "warn": warn, "fail": err}
    first_next: str | None = None
    for item in result.checks:
        if item.status == "fail" and first_next is None and item.next:
            first_next = item.next
        if item.status == "ok" and _state.quiet:
            continue
        text = item.name if not item.detail else f"{item.name}  {item.detail}"
        printers[item.status](text)
    for note in result.notes:
        if note.startswith("duplicate IDs need"):
            warn(note)
        else:
            write_line(note)
    if first_next:
        next_hint(first_next)


def render_import(result: object) -> None:
    """Preview, or the write summary. Candidates stay unaccepted."""
    from costanza.importers import ImportReport

    assert isinstance(result, ImportReport)
    count = len(result.candidates)
    skipped = len(result.skipped)
    if result.wrote:
        total = result.proposed + result.duplicate
        ok(
            f"imported {total} ({result.proposed} proposed, {result.duplicate} duplicate) "
            f"from {result.path.name}"
        )
        if result.redacted:
            warn(f"redacted {len(result.redacted)} secret(s) ({', '.join(result.redacted)})")
        for message in result.warnings:
            warn(message)
        next_hint("cz review")
        return
    write_line(
        f"{result.source}: {count} candidates, {skipped} skipped, low confidence; nothing written"
    )
    shown = result.candidates[:8]
    for item in shown:
        line = f"  {item.kind}  {item.text}"
        if item.why:
            line += f" -- {item.why}"
        write_line(line)
    extra = count - len(shown)
    if extra:
        write_line(f"  and {extra} more")
    for message in result.skipped[:8]:
        warn(message)
    if result.truncated:
        warn("file ended inside an open block; that part was skipped")
    if count:
        next_hint(f"cz import {result.source} {result.path} --yes")


# Original 7x6 face. "#" marks ink; the block banner substitutes U+2588.
_WELCOME_WORD = "COSTANZA"
_WELCOME_FONT: dict[str, tuple[str, ...]] = {
    "C": ("######", "#     ", "#     ", "#     ", "#     ", "#     ", "######"),
    "O": ("######", "#    #", "#    #", "#    #", "#    #", "#    #", "######"),
    "S": ("######", "#     ", "#     ", "######", "     #", "     #", "######"),
    "T": ("######", "  ##  ", "  ##  ", "  ##  ", "  ##  ", "  ##  ", "  ##  "),
    "A": ("######", "#    #", "#    #", "######", "#    #", "#    #", "#    #"),
    "N": ("#    #", "##   #", "# #  #", "#  # #", "#   ##", "#    #", "#    #"),
    "Z": ("######", "    ##", "   ## ", "  ##  ", " ##   ", "##    ", "######"),
}
_WELCOME_BLOCK = "\u2588"
# 256-color ramp: deep red at the top through orange at the bottom.
_WELCOME_ROW_COLORS = (124, 160, 196, 202, 208, 214, 220)
_WELCOME_DIM = "color(245)"
_WELCOME_BG = "#14100f"
_WELCOME_BORDER = "#ff8c00"
TAGLINE = "One small file so the next AI chat can continue your project."
HELP_LINE = "costanza --help for all commands"
_WELCOME_COMMANDS: tuple[tuple[str, str], ...] = (
    ("init", "Create the handoff file in here"),
    ("decide", "Propose a decision and its reason"),
    ("review", "Accept or reject waiting proposals now"),
    ("handoff", "Print a packet for new chats"),
    ("paste", "Read a pasted reply into proposals"),
)
_WELCOME_PLAIN_WIDTH = 60


def _welcome_rows(glyph: str) -> tuple[str, ...]:
    height = len(_WELCOME_FONT["C"])
    rows: list[str] = []
    for index in range(height):
        parts = [_WELCOME_FONT[letter][index].replace("#", glyph) for letter in _WELCOME_WORD]
        rows.append(" ".join(parts))
    return tuple(rows)


def _blocks_ok() -> bool:
    if _state.ascii:
        return False
    encoding = sys.stdout.encoding or "utf-8"
    try:
        _WELCOME_BLOCK.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _welcome_plain() -> bool:
    if _state.quiet or _state.no_color or not sys.stdout.isatty():
        return True
    return display_width() < _WELCOME_PLAIN_WIDTH


def _welcome_body(version: str) -> list[str]:
    width = max(len(name) for name, _desc in _WELCOME_COMMANDS)
    lines = [TAGLINE, "", f"costanza {version}"]
    lines.extend(f"{name.ljust(width)}  {desc}" for name, desc in _WELCOME_COMMANDS)
    lines.append("")
    lines.append(HELP_LINE)
    return lines


def _welcome_console() -> Console:
    return Console(
        file=sys.stdout,
        highlight=False,
        emoji=False,
        soft_wrap=True,
        no_color=False,
        force_terminal=True,
        color_system="truecolor",
        width=min(80, display_width()),
        legacy_windows=False,
    )


def _panel_size(lines: list[str]) -> tuple[int, int, int]:
    """Panel width, inner width, and horizontal padding. Width never exceeds 80."""
    longest = max((len(line) for line in lines), default=0)
    screen = min(80, display_width())
    pad = 1 if screen >= longest + 4 else 0
    width = min(screen, longest + 2 + pad * 2)
    inner = max(1, width - 2 - pad * 2)
    return width, inner, pad


def _ink(text: str, inner: int, *, color: str) -> Text:
    shown = text if len(text) <= inner else text[:inner]
    return Text(
        shown.ljust(inner),
        style=Style(color=color, bgcolor=_WELCOME_BG),
        no_wrap=True,
        overflow="crop",
    )


def _welcome_panel(version: str) -> Panel:
    body = _welcome_body(version)
    rows = list(_welcome_rows(_WELCOME_BLOCK))
    width, inner, pad = _panel_size([*rows, *body])
    lines: list[Text] = [
        _ink(row, inner, color=f"color({_WELCOME_ROW_COLORS[index]})") for index, row in enumerate(rows)
    ]
    lines.extend(_ink(line, inner, color=_WELCOME_DIM) for line in body)
    return Panel(
        Group(*lines),
        box=box.ROUNDED,
        border_style=Style(color=_WELCOME_BORDER),
        style=Style(bgcolor=_WELCOME_BG),
        width=width,
        padding=(0, pad),
        expand=True,
    )


def _print_ascii_welcome(version: str) -> None:
    """Hash banner with foreground colour only. No panel and no background."""
    console = _welcome_console()
    for index, row in enumerate(_welcome_rows("#")):
        console.print(
            row,
            style=f"color({_WELCOME_ROW_COLORS[index]})",
            overflow="ignore",
            highlight=False,
        )
    console.print("", highlight=False)
    for line in _welcome_body(version):
        console.print(line, style=_WELCOME_DIM, overflow="ignore", highlight=False)


def render_welcome(version: str) -> None:
    """Print the welcome screen. Plain text when colour, a tty, or width is unavailable."""
    if _welcome_plain():
        for line in _welcome_body(version):
            write_raw(line)
        return
    if not _blocks_ok():
        _print_ascii_welcome(version)
        return
    _welcome_console().print(_welcome_panel(version))
