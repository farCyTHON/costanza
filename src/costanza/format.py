"""Strict Costanza Format v1 (CF1) parser, writer and validator.

Pure library: text in, structures out. No Rich, Typer, network or
filesystem access. Callers that need archive IDs pass those file
contents in as text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from costanza.constants import HEADER_KEYS, KINDS, KNOWN_SECTIONS, MARKER_CANONICAL, NOW_KEYS
from costanza.tokens import active_count as estimate_tokens

# Stable finding codes. Numbers stay fixed; new rules take the next free id.
CF001 = "CF001"  # missing first-line marker
CF002 = "CF002"  # unsupported / future format version
CF003 = "CF003"  # missing or empty PROJECT line
CF004 = "CF004"  # line not understood
CF005 = "CF005"  # entry in the wrong section
CF006 = "CF006"  # duplicate ID
CF007 = "CF007"  # malformed ID
CF008 = "CF008"  # line over 300 characters
CF009 = "CF009"  # forbidden character
CF010 = "CF010"  # duplicate header or NOW key
CF011 = "CF011"  # X entry without a reason
CF012 = "CF012"  # duplicate known section
CF013 = "CF013"  # unsafe file reference
CF014 = "CF014"  # IDs out of order
CF015 = "CF015"  # line over the soft limit
CF016 = "CF016"  # unknown header key
CF017 = "CF017"  # header value is ?

SOFT_LINE_LIMIT = 160
HARD_LINE_LIMIT = 300
PROJECT_MAX = 120
HEADER_VALUE_MAX = 300
MAX_FILES = 8
MAX_PATH_LEN = 200

MARKER_RE = re.compile(r"^<!-- costanza v(\d+)(?: \|[^\n]*)? -->$")
PROJECT_RE = re.compile(r"^# PROJECT:\s*(.*)$")
HEADER_SPLIT_RE = re.compile(r"\s\|\s(?=(stack|run|test|layout|synced):\s)")
PAIR_RE = re.compile(r"^([a-z][a-z0-9_-]*):\s*(.*)$")
VALID_ID_RE = re.compile(r"^([DXRGQ])([1-9][0-9]*)(?:\s+|$)")
ANY_ID_RE = re.compile(r"^([A-Za-z])(\d+)")
SHA_TAIL_RE = re.compile(r" @([0-9a-f]{7,12})$")
SHA_RE = re.compile(r"^[0-9a-f]{7,12}$")
ENTRY_LINE_RE = re.compile(r"^([DXRGQ])([1-9][0-9]*)(?:\s|$)")
LEDGER_RE = re.compile(r"^([DXRGQ]) (\d+)$")
DRIVE_RE = re.compile(r"^[A-Za-z]:")

KIND_TO_HEADING = {
    "D": "## DECISIONS",
    "X": "## REJECTED",
    "R": "## RULES",
    "G": "## GOTCHAS",
    "Q": "## OPEN",
}
HEADING_TO_ATTR = {
    "## DECISIONS": "decisions",
    "## REJECTED": "rejected",
    "## RULES": "rules",
    "## GOTCHAS": "gotchas",
    "## OPEN": "open",
}
SECTION_ORDER = ("## DECISIONS", "## REJECTED", "## RULES", "## GOTCHAS", "## OPEN")
ANCHORS = ("header", "NOW", *SECTION_ORDER)
KNOWN_HEADINGS = frozenset({"## NOW", *KNOWN_SECTIONS})
PATH_PUNCT = frozenset("._-/+@~*")

_FORBIDDEN_RANGES = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x200B, 0x200D),
    (0x202A, 0x202E),
    (0x2066, 0x2069),
)
_FORBIDDEN_SINGLE = frozenset({0x2060, 0xFEFF})


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    line: int
    message: str
    path: str = "COSTANZA.md"
    hint: str = ""


@dataclass
class Header:
    project: str
    stack: str = "?"
    run: str = "?"
    test: str = "?"
    layout: str = "?"
    synced: str = "never"
    extras: tuple[tuple[str, str], ...] = ()
    line: int = field(default=2, compare=False)


@dataclass
class Now:
    doing: str = "none"
    done: str = "none"
    next: str = "none"
    blocked: str = "none"
    line: int = field(default=0, compare=False)


@dataclass
class Entry:
    kind: str
    number: int
    text: str
    reason: str | None = None
    sha: str | None = None
    files: tuple[str, ...] = ()
    line: int = field(default=0, compare=False)
    raw: str = field(default="", compare=False)

    @property
    def id(self) -> str:
        return f"{self.kind}{self.number}"


@dataclass(frozen=True)
class Extra:
    """Unknown section or HTML comment, kept verbatim."""

    text: str
    after: str
    line: int = field(default=0, compare=False)


@dataclass
class Document:
    header: Header
    now: Now
    decisions: tuple[Entry, ...] = ()
    rejected: tuple[Entry, ...] = ()
    rules: tuple[Entry, ...] = ()
    gotchas: tuple[Entry, ...] = ()
    open: tuple[Entry, ...] = ()
    extras: tuple[Extra, ...] = ()
    version: int = 1
    readable: bool = True
    marker_ok: bool = True
    source_lines: tuple[str, ...] = field(default=(), compare=False)
    stray: tuple[tuple[int, str, str], ...] = field(default=(), compare=False)

    def entries_of(self, kind: str) -> tuple[Entry, ...]:
        return {
            "D": self.decisions,
            "X": self.rejected,
            "R": self.rules,
            "G": self.gotchas,
            "Q": self.open,
        }[kind]

    def all_entries(self) -> tuple[Entry, ...]:
        return self.decisions + self.rejected + self.rules + self.gotchas + self.open


@dataclass(frozen=True)
class Pack:
    """A budget-trimmed document to hand to an agent."""

    text: str
    tokens: int
    cut: tuple[str, ...]


def _empty_document(*, version: int = 0, readable: bool = False, marker_ok: bool = False) -> Document:
    return Document(
        header=Header(project=""),
        now=Now(),
        version=version,
        readable=readable,
        marker_ok=marker_ok,
    )


def _norm(value: str) -> str:
    value = value.replace("\t", " ")
    value = " ".join(value.split())
    return unicodedata.normalize("NFC", value)


def forbidden_char_label(text: str) -> str | None:
    """Return a display label for the first forbidden control or bidi character."""
    for char in text:
        code = ord(char)
        for start, end in _FORBIDDEN_RANGES:
            if start <= code <= end:
                return f"U+{code:04X}"
        if code in _FORBIDDEN_SINGLE:
            return f"U+{code:04X}"
    return None


def forbidden_label(text: str) -> str | None:
    """Return a display label for the first forbidden character or ``-->``."""
    if "-->" in text:
        return "-->"
    return forbidden_char_label(text)


def path_problem(path: str) -> str | None:
    """Return a fix-it phrase if ``path`` is not a safe repo-relative path."""
    if not path:
        return "path is empty; use a repo-relative path like app/db.py"
    if len(path) > MAX_PATH_LEN:
        return f"path is {len(path)} characters; shorten it to at most {MAX_PATH_LEN}"
    if path.startswith("/"):
        return "path is absolute; use a repo-relative path with / separators"
    if DRIVE_RE.match(path):
        return "path has a drive letter; use a repo-relative path with / separators"
    if "\\" in path:
        return "path uses \\; replace backslashes with /"
    if "\x00" in path:
        return "path contains a NUL byte; remove it"
    for segment in path.split("/"):
        if segment == "":
            return "path has an empty segment; remove duplicate /"
        if segment == ".":
            return "path contains a '.' segment; remove it"
        if segment == "..":
            return "path contains '..'; use a repo-relative path with no parent segments"
        for char in segment:
            if char in PATH_PUNCT or char.isalnum():
                continue
            return (
                f"path has a forbidden character {char!r}; "
                "allowed: letters, digits, . _ - / + @ ~ *"
            )
    return None


def parse_entry_line(line: str) -> Entry | None:
    """Parse one CF1 entry line. Returns None if the line has no valid ID."""
    match = VALID_ID_RE.match(line)
    if match is None:
        return None
    kind = match.group(1)
    number = int(match.group(2))
    rest = line[match.end() :]
    files: list[str] = []
    sha: str | None = None
    if rest.endswith("]") and " [files: " in rest:
        idx = rest.rfind(" [files: ")
        files_part = rest[idx + len(" [files: ") : -1]
        files = [part.strip() for part in files_part.split(", ")] if files_part else []
        rest = rest[:idx]
    sha_match = SHA_TAIL_RE.search(rest)
    if sha_match:
        sha = sha_match.group(1)
        rest = rest[: sha_match.start()]
    reason: str | None = None
    if " -- " in rest:
        text, reason = rest.split(" -- ", 1)
    else:
        text = rest
    text = text.strip()
    if reason is not None:
        reason = reason.strip()
    return Entry(kind=kind, number=number, text=text, reason=reason, sha=sha, files=tuple(files), raw=line)


def render_entry(entry: Entry) -> str:
    line = f"{entry.id} {entry.text}"
    if entry.reason:
        line = f"{entry.id} {entry.text} -- {entry.reason}"
    if entry.sha:
        line += f" @{entry.sha}"
    if entry.files:
        line += f" [files: {', '.join(entry.files)}]"
    return line


def length_warning(line: str, *, review: bool = False) -> str | None:
    """Warn when a composed entry line would exceed the soft limit.

    Returns None when the line fits. Review adds a hint to edit first.
    """
    if len(line) <= SOFT_LINE_LIMIT:
        return None
    message = f"this will be {len(line)} characters; limit {SOFT_LINE_LIMIT}, shorten it"
    if review:
        message += "; press e before accepting"
    return message


def _header_parts(line: str) -> list[tuple[str, str]] | None:
    parts: list[tuple[str, str]] = []
    rest = line
    while True:
        match = HEADER_SPLIT_RE.search(rest)
        if match is None:
            pair = PAIR_RE.match(rest)
            if pair:
                parts.append((pair.group(1), pair.group(2).strip()))
            elif rest.strip():
                return None
            break
        pair = PAIR_RE.match(rest[: match.start()])
        if pair:
            parts.append((pair.group(1), pair.group(2).strip()))
        else:
            return None
        rest = rest[match.end() :]
    return parts


def _is_comment_start(line: str) -> bool:
    return line.strip().startswith("<!--")


def _collect_comment(lines: list[str], start: int) -> tuple[str, int]:
    """Return (verbatim text, index after the comment)."""
    collected = [lines[start]]
    index = start + 1
    if "-->" in lines[start]:
        return lines[start], index
    while index < len(lines):
        collected.append(lines[index])
        if "-->" in lines[index]:
            index += 1
            break
        index += 1
    return "\n".join(collected), index


def _trim_trailing_blanks(body: list[str]) -> list[str]:
    while body and body[-1].strip() == "":
        body.pop()
    return body


def parse(text: str) -> Document:
    """Parse CF1. Records 1-based line numbers. Does not raise on content."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines:
        doc = _empty_document()
        doc.source_lines = ()
        return doc

    first = lines[0].rstrip()
    match = MARKER_RE.match(first)
    if match is None:
        doc = _empty_document()
        doc.source_lines = tuple(lines)
        return doc
    version = int(match.group(1))
    if version != 1:
        doc = _empty_document(version=version, marker_ok=True)
        doc.source_lines = tuple(lines)
        return doc

    header = Header(project="")
    now = Now()
    extras: list[Extra] = []
    stray: list[tuple[int, str, str]] = []
    seen_sections: set[str] = set()
    last_anchor = "header"

    index = 1
    if index < len(lines):
        proj = PROJECT_RE.match(lines[index].rstrip())
        if proj is not None:
            header.project = proj.group(1).strip()
            header.line = index + 1
            index += 1

    known: dict[str, str] = {}
    extra_pairs: list[tuple[str, str]] = []
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if stripped == "":
            index += 1
            break
        if stripped.startswith("## "):
            break
        if _is_comment_start(raw):
            start = index
            comment, index = _collect_comment(lines, index)
            extras.append(Extra(text=comment, after="header", line=start + 1))
            continue
        parts = _header_parts(stripped)
        if parts is None:
            stray.append((index + 1, "header", raw.rstrip()))
            index += 1
            continue
        for key, value in parts:
            if key in HEADER_KEYS:
                if key in known:
                    stray.append((index + 1, "header-dup", key))
                else:
                    known[key] = value
            else:
                extra_pairs.append((key, value))
        index += 1

    header.stack = known.get("stack", "?")
    header.run = known.get("run", "?")
    header.test = known.get("test", "?")
    header.layout = known.get("layout", "?")
    header.synced = known.get("synced", "never")
    header.extras = tuple(extra_pairs)

    current: str | None = None
    unknown_body: list[str] | None = None
    unknown_start = 0
    seen_now: set[str] = set()
    section_items: dict[str, list[Entry]] = {heading: [] for heading in SECTION_ORDER}

    def flush_unknown() -> None:
        nonlocal unknown_body, unknown_start
        if unknown_body is None:
            return
        body = _trim_trailing_blanks(list(unknown_body))
        extras.append(Extra(text="\n".join(body), after=last_anchor, line=unknown_start))
        unknown_body = None

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if unknown_body is not None and not stripped.startswith("## "):
            unknown_body.append(raw)
            index += 1
            continue
        if stripped == "":
            index += 1
            continue
        if stripped.startswith("## "):
            flush_unknown()
            heading = stripped
            if heading in KNOWN_HEADINGS:
                if heading in seen_sections:
                    stray.append((index + 1, "dup-section", heading))
                seen_sections.add(heading)
                current = heading
                last_anchor = "NOW" if heading == "## NOW" else heading
                if heading == "## NOW":
                    now.line = index + 1
                index += 1
                continue
            unknown_body = [raw]
            unknown_start = index + 1
            current = None
            index += 1
            continue
        if current == "## NOW":
            if _is_comment_start(raw):
                start = index
                comment, index = _collect_comment(lines, index)
                extras.append(Extra(text=comment, after="NOW", line=start + 1))
                continue
            pair = PAIR_RE.match(stripped)
            if pair and pair.group(1) in NOW_KEYS:
                key = pair.group(1)
                value = pair.group(2).strip() or "none"
                if key in seen_now:
                    stray.append((index + 1, "now-dup", key))
                else:
                    seen_now.add(key)
                    setattr(now, key, value)
            else:
                stray.append((index + 1, "NOW", raw.rstrip()))
            index += 1
            continue
        if current in KNOWN_SECTIONS:
            if _is_comment_start(raw):
                start = index
                comment, index = _collect_comment(lines, index)
                extras.append(Extra(text=comment, after=current, line=start + 1))
                continue
            entry = parse_entry_line(stripped)
            if entry is None:
                if ANY_ID_RE.match(stripped):
                    stray.append((index + 1, "malformed", stripped))
                else:
                    stray.append((index + 1, current, raw.rstrip()))
            else:
                entry.line = index + 1
                entry.raw = raw.rstrip()
                section_items[current].append(entry)
            index += 1
            continue
        if _is_comment_start(raw):
            flush_unknown()
            start = index
            comment, index = _collect_comment(lines, index)
            extras.append(Extra(text=comment, after=last_anchor, line=start + 1))
            continue
        stray.append((index + 1, last_anchor, raw.rstrip()))
        index += 1

    flush_unknown()
    return Document(
        header=header,
        now=now,
        decisions=tuple(section_items["## DECISIONS"]),
        rejected=tuple(section_items["## REJECTED"]),
        rules=tuple(section_items["## RULES"]),
        gotchas=tuple(section_items["## GOTCHAS"]),
        open=tuple(section_items["## OPEN"]),
        extras=tuple(extras),
        version=1,
        readable=True,
        marker_ok=True,
        source_lines=tuple(lines),
        stray=tuple(stray),
    )


def _header_block(header: Header) -> str:
    lines = [
        MARKER_CANONICAL,
        f"# PROJECT: {header.project}",
        f"stack: {_norm(header.stack) if header.stack else '?'}",
        f"run: {_norm(header.run) if header.run else '?'} | test: {_norm(header.test) if header.test else '?'}",
        f"layout: {_norm(header.layout) if header.layout else '?'}",
        f"synced: {_norm(header.synced) if header.synced else 'never'}",
    ]
    for key, value in header.extras:
        lines.append(f"{key}: {_norm(value)}")
    return "\n".join(lines)


def _now_block(now: Now) -> str:
    return "\n".join(
        [
            "## NOW",
            f"doing: {_norm(now.doing) if now.doing else 'none'}",
            f"done: {_norm(now.done) if now.done else 'none'}",
            f"next: {_norm(now.next) if now.next else 'none'}",
            f"blocked: {_norm(now.blocked) if now.blocked else 'none'}",
        ]
    )


def _section_block(heading: str, entries: tuple[Entry, ...]) -> str:
    ordered = sorted(entries, key=lambda item: item.number)
    lines = [heading, *[render_entry(item) for item in ordered]]
    return "\n".join(lines)


def _attach(block: str, extras: list[Extra]) -> str:
    if not extras:
        return block
    parts = [block, *[item.text for item in extras]]
    return "\n\n".join(parts)


def render(document: Document) -> str:
    """Write the canonical CF1 form (LF, no BOM, one final newline)."""
    grouped: dict[str, list[Extra]] = {anchor: [] for anchor in ANCHORS}
    for extra in document.extras:
        grouped.setdefault(extra.after, []).append(extra)

    blocks = [
        _attach(_header_block(document.header), grouped.get("header", [])),
        _attach(_now_block(document.now), grouped.get("NOW", [])),
    ]
    for heading in SECTION_ORDER:
        attr = HEADING_TO_ATTR[heading]
        entries: tuple[Entry, ...] = getattr(document, attr)
        blocks.append(_attach(_section_block(heading, entries), grouped.get(heading, [])))
    return "\n\n".join(blocks) + "\n"


def _finding(code: str, severity: str, line: int, message: str) -> Finding:
    return Finding(code=code, severity=severity, line=line, message=f"line {line}: {message}")


def _scan_line_findings(lines: tuple[str, ...]) -> list[Finding]:
    findings: list[Finding] = []
    for number, raw in enumerate(lines, start=1):
        label = forbidden_char_label(raw)
        if label is not None:
            findings.append(
                _finding(
                    CF009,
                    "error",
                    number,
                    f"forbidden character {label}; remove it (or replace a tab with a space)",
                )
            )
        # ``-->`` is legal in the marker and in HTML comments; it is not
        # legal in header, NOW, entry or unknown-section prose.
        if "-->" in raw and not _is_comment_start(raw) and raw.strip() != "-->":
            findings.append(
                _finding(
                    CF009,
                    "error",
                    number,
                    "forbidden sequence -->; remove it so the line is not an HTML comment closer",
                )
            )
        length = len(raw)
        if length > HARD_LINE_LIMIT:
            findings.append(
                _finding(
                    CF008,
                    "error",
                    number,
                    f"line is {length} characters; shorten it to at most {HARD_LINE_LIMIT}",
                )
            )
        elif length > SOFT_LINE_LIMIT:
            findings.append(
                _finding(
                    CF015,
                    "warning",
                    number,
                    f"line is {length} characters; keep it at or under {SOFT_LINE_LIMIT}",
                )
            )
    return findings


def validate(document: Document) -> list[Finding]:
    """Return findings with a stable code, severity, line and a fix-it message."""
    if not document.marker_ok:
        return [
            _finding(
                CF001,
                "error",
                1,
                "missing first-line marker; add exactly: "
                f"{MARKER_CANONICAL}",
            )
        ]
    if document.version != 1:
        return [
            _finding(
                CF002,
                "error",
                1,
                f"unsupported format version {document.version}; "
                "this tool reads Costanza Format v1 only. Change the marker to "
                f"{MARKER_CANONICAL}",
            )
        ]

    findings: list[Finding] = []
    lines = document.source_lines if document.source_lines else tuple(render(document).splitlines())
    findings.extend(_scan_line_findings(lines))

    project = document.header.project
    proj_line = document.header.line or 2
    if not project:
        findings.append(
            _finding(
                CF003,
                "error",
                proj_line,
                "missing or empty # PROJECT: line; add `# PROJECT: <name>` as line 2 "
                f"(1 to {PROJECT_MAX} characters)",
            )
        )
    elif len(project) > PROJECT_MAX:
        findings.append(
            _finding(
                CF003,
                "error",
                proj_line,
                f"PROJECT value is {len(project)} characters; shorten it to at most {PROJECT_MAX}",
            )
        )

    for key in HEADER_KEYS:
        value = getattr(document.header, key)
        if len(value) > HEADER_VALUE_MAX:
            findings.append(
                _finding(
                    CF008,
                    "error",
                    document.header.line,
                    f"header {key} is {len(value)} characters; shorten it to at most {HEADER_VALUE_MAX}",
                )
            )
        if key != "synced" and value == "?":
            findings.append(
                _finding(
                    CF017,
                    "warning",
                    document.header.line,
                    f"header {key} is '?'; replace it with the real value or leave it for cz scan",
                )
            )
    for key, _value in document.header.extras:
        findings.append(
            _finding(
                CF016,
                "warning",
                document.header.line,
                f"unknown header key {key}; move it to an unknown section or drop it",
            )
        )

    seen_ids: dict[str, int] = {}
    for entry in document.all_entries():
        line = entry.line or 1
        if entry.id in seen_ids:
            findings.append(
                _finding(
                    CF006,
                    "error",
                    line,
                    f"duplicate ID {entry.id}; give this entry a new unused {entry.kind} ID "
                    f"or delete the extra line (first {entry.id} is at line {seen_ids[entry.id]})",
                )
            )
        else:
            seen_ids[entry.id] = line
        if not entry.text:
            findings.append(
                _finding(
                    CF004,
                    "error",
                    line,
                    f"{entry.id} has empty text; write the {entry.kind} text after the ID",
                )
            )
        if entry.reason == "":
            findings.append(
                _finding(
                    CF004,
                    "error",
                    line,
                    f"{entry.id} has an empty reason; write text after ' -- ' or remove ' -- '",
                )
            )
        if entry.kind == "X" and not entry.reason:
            findings.append(
                _finding(
                    CF011,
                    "error",
                    line,
                    f"{entry.id} is a rejected idea and needs a reason; write "
                    f"`{entry.id} <idea> -- <why it was ruled out>`",
                )
            )
        if entry.text.startswith("#"):
            findings.append(
                _finding(
                    CF004,
                    "error",
                    line,
                    f"{entry.id} text starts with #; rewrite the text so it does not look like a heading",
                )
            )
        if entry.sha is not None and SHA_RE.match(entry.sha) is None:
            findings.append(
                _finding(
                    CF004,
                    "error",
                    line,
                    f"{entry.id} has a bad @sha; use 7 to 12 lowercase hex characters",
                )
            )
        if len(entry.files) > MAX_FILES:
            findings.append(
                _finding(
                    CF013,
                    "error",
                    line,
                    f"{entry.id} lists {len(entry.files)} files; keep at most {MAX_FILES}",
                )
            )
        for path in entry.files:
            problem = path_problem(path)
            if problem is not None:
                findings.append(
                    _finding(CF013, "error", line, f"{entry.id} [files: {path}] {problem}")
                )

    for kind in KINDS:
        numbers = [item.number for item in document.entries_of(kind)]
        if numbers != sorted(numbers):
            line = document.entries_of(kind)[0].line or 1
            findings.append(
                _finding(
                    CF014,
                    "warning",
                    line,
                    f"{kind} IDs are out of order; write them in ascending number "
                    f"({kind}1 then {kind}2) — the writer will sort them",
                )
            )

    for line, context, payload in document.stray:
        if context == "header-dup" or context == "now-dup":
            findings.append(
                _finding(
                    CF010,
                    "error",
                    line,
                    f"duplicate key {payload}; keep only one {payload}: line and delete the extra",
                )
            )
        elif context == "dup-section":
            findings.append(
                _finding(
                    CF012,
                    "error",
                    line,
                    f"duplicate section {payload}; keep the first {payload} and merge or delete the extra",
                )
            )
        elif context == "malformed":
            findings.append(
                _finding(
                    CF007,
                    "error",
                    line,
                    f"malformed ID in {payload!r}; use a kind letter D/X/R/G/Q plus a number "
                    "with no leading zero (D1, not D0 or D01)",
                )
            )
        elif context in KNOWN_SECTIONS:
            findings.append(
                _finding(
                    CF004,
                    "error",
                    line,
                    f"line not understood in {context}; each line must be "
                    f"`{KNOWN_SECTIONS[context]}<n> <text>` or an HTML comment",
                )
            )
        else:
            findings.append(
                _finding(
                    CF004,
                    "error",
                    line,
                    f"line not understood ({context}); fix the line so it is a "
                    "header key, a NOW key, an entry, a ## heading, or an HTML comment",
                )
            )

    # Wrong-section entries that parsed (valid ID, other kind).
    for heading, attr in HEADING_TO_ATTR.items():
        expected = KNOWN_SECTIONS[heading]
        for entry in getattr(document, attr):
            if entry.kind != expected:
                findings.append(
                    _finding(
                        CF005,
                        "error",
                        entry.line or 1,
                        f"{entry.id} is under {heading}; move it to {KIND_TO_HEADING[entry.kind]}",
                    )
                )

    findings.sort(key=lambda item: (item.line, item.code, item.message))
    return findings


def ids_in_text(text: str) -> dict[str, int]:
    """Highest ID number per kind found in CF1, archive, or ledger text."""
    marks = {kind: 0 for kind in KINDS}
    for raw in text.splitlines():
        stripped = raw.strip()
        ledger = LEDGER_RE.match(stripped)
        if ledger:
            marks[ledger.group(1)] = max(marks[ledger.group(1)], int(ledger.group(2)))
            continue
        entry = ENTRY_LINE_RE.match(stripped)
        if entry:
            marks[entry.group(1)] = max(marks[entry.group(1)], int(entry.group(2)))
    return marks


def high_water(document: Document, *archive_texts: str) -> dict[str, int]:
    """High-water mark per kind from the document plus archive/ledger texts.

    An ID is never reused: the next number is one above the highest ID
    ever seen in the file or in ``.costanza/archive/`` (including the
    ``ids`` ledger if that text is passed in).
    """
    marks = {kind: 0 for kind in KINDS}
    for entry in document.all_entries():
        marks[entry.kind] = max(marks[entry.kind], entry.number)
    for text in archive_texts:
        for kind, number in ids_in_text(text).items():
            marks[kind] = max(marks[kind], number)
    return marks


def next_id(kind: str, document: Document, *archive_texts: str) -> str:
    """Next ID for ``kind`` (D/X/R/G/Q), never reusing a retired number."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")
    return f"{kind}{high_water(document, *archive_texts)[kind] + 1}"


def next_ids(document: Document, *archive_texts: str) -> dict[str, str]:
    """Next ID for every kind."""
    return {kind: next_id(kind, document, *archive_texts) for kind in KINDS}


def _subset(document: Document, keep: set[str], extras: tuple[Extra, ...]) -> Document:
    return Document(
        header=document.header,
        now=document.now,
        decisions=tuple(item for item in document.decisions if item.id in keep),
        rejected=tuple(item for item in document.rejected if item.id in keep),
        rules=tuple(item for item in document.rules if item.id in keep),
        gotchas=tuple(item for item in document.gotchas if item.id in keep),
        open=tuple(item for item in document.open if item.id in keep),
        extras=extras,
        version=document.version,
        readable=document.readable,
        marker_ok=document.marker_ok,
    )


def compile_to_budget(document: Document, budget: int) -> Pack:
    """Pack the document for an agent, cutting whole entries only.

    Include order: header, NOW, RULES, DECISIONS, REJECTED, GOTCHAS, OPEN.
    Unknown sections and HTML comments are appended as whole blocks after
    the known block they follow. A line is never split.
    """
    if not document.readable or not document.marker_ok or document.version != 1:
        text = render(document) if document.readable else ""
        return Pack(text=text, tokens=estimate_tokens(text) if text else 0, cut=())

    keep: set[str] = set()
    cut: list[str] = []
    extras_keep: list[Extra] = []
    priority = (
        document.rules,
        document.decisions,
        document.rejected,
        document.gotchas,
        document.open,
    )
    for group in priority:
        for entry in group:
            trial = _subset(document, keep | {entry.id}, tuple(extras_keep))
            if estimate_tokens(render(trial)) <= budget:
                keep.add(entry.id)
            else:
                cut.append(entry.id)
    for extra in document.extras:
        trial = _subset(document, keep, tuple(extras_keep + [extra]))
        if estimate_tokens(render(trial)) <= budget:
            extras_keep.append(extra)
        else:
            label = extra.text.splitlines()[0] if extra.text else "extra"
            cut.append(label)
    packed = _subset(document, keep, tuple(extras_keep))
    text = render(packed)
    return Pack(text=text, tokens=estimate_tokens(text), cut=tuple(cut))
