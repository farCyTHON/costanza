"""Install and remove the Costanza instruction block in other tools' files.

The block between ``<!-- costanza:begin v1 -->`` and ``<!-- costanza:end -->``
is the only text Costanza writes into those files. Bytes outside the markers
are never changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from costanza.config import load_config
from costanza.constants import (
    AGENT_BLOCK,
    AGENT_VERSION,
    ALWAYS_CREATE_RELATIVE,
    DEFAULT_AGENT_RELATIVE,
    MDC_DESCRIPTION,
    MDC_FRONTMATTER,
)
from costanza.io import write_bytes
from costanza.paths import ProjectPaths, discover_root

BEGIN_RE = re.compile(r"^<!-- costanza:begin v(\d+) -->\s*$")
END_RE = re.compile(r"^<!-- costanza:end -->\s*$")
BOM = b"\xef\xbb\xbf"
MDC_NAME = "costanza.mdc"


@dataclass
class AgentRow:
    path: str
    status: str
    detail: str = ""
    written: bool = False


@dataclass
class AgentsResult:
    rows: list[AgentRow] = field(default_factory=list)
    failed: bool = False


def _block_for(newline: str) -> str:
    text = AGENT_BLOCK
    if not text.endswith("\n"):
        text += "\n"
    if newline == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def _mdc_for(newline: str) -> str:
    text = MDC_FRONTMATTER + AGENT_BLOCK
    if not text.endswith("\n"):
        text += "\n"
    if newline == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def _decode(data: bytes) -> tuple[bytes, str]:
    if data.startswith(BOM):
        return BOM, data[3:].decode("utf-8")
    return b"", data.decode("utf-8")


def _encode(bom: bytes, text: str) -> bytes:
    return bom + text.encode("utf-8")


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _lines(text: str) -> list[str]:
    if not text:
        return []
    return text.splitlines()


def _join(lines: list[str], newline: str, *, ended: bool) -> str:
    if not lines:
        return ""
    body = newline.join(lines)
    if ended and not body.endswith(newline):
        body += newline
    return body


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_mdc(path: Path) -> bool:
    return path.name.lower() == MDC_NAME


def resolve_existing(root: Path, relative: str) -> Path | None:
    """Return an existing path matching ``relative``, case-insensitive."""
    wanted = Path(relative)
    direct = root / wanted
    if direct.exists():
        return direct
    parent = (root / wanted).parent
    name = wanted.name
    if not parent.is_dir():
        return None
    try:
        for child in parent.iterdir():
            if child.name.lower() == name.lower():
                return child
    except OSError:
        return None
    return None


def _default_targets(root: Path, mode: str) -> list[Path]:
    chosen: list[Path] = []
    for relative in DEFAULT_AGENT_RELATIVE:
        existing = resolve_existing(root, relative)
        create = False
        if mode == "all":
            create = True
        elif relative in ALWAYS_CREATE_RELATIVE:
            create = True
        elif relative == ".cursor/rules/costanza.mdc":
            create = (root / ".cursor").is_dir()
        if existing is not None:
            chosen.append(existing)
        elif create:
            chosen.append(root / relative)
    return chosen


def select_targets(
    root: Path,
    *,
    mode: str = "auto",
    extra: list[Path] | None = None,
    configured: tuple[str, ...] = (),
) -> list[Path]:
    if extra:
        out: list[Path] = []
        for item in extra:
            path = item if item.is_absolute() else root / item
            relative = path.name
            try:
                relative = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                relative = path.as_posix()
            found = resolve_existing(root, relative)
            out.append(found if found is not None else path)
        return out
    if configured:
        out = []
        for relative in configured:
            found = resolve_existing(root, relative)
            out.append(found if found is not None else root / relative)
        return out
    if mode == "none":
        return []
    return _default_targets(root, mode)


def _marker_spans(lines: list[str]) -> tuple[list[int], list[int]]:
    begins = [index for index, line in enumerate(lines) if BEGIN_RE.match(line.rstrip())]
    ends = [index for index, line in enumerate(lines) if END_RE.match(line.rstrip())]
    return begins, ends


def _begin_version(line: str) -> int | None:
    match = BEGIN_RE.match(line.rstrip())
    if match is None:
        return None
    return int(match.group(1))


def _mdc_is_ours(text: str) -> bool:
    for line in text.splitlines()[:12]:
        stripped = line.strip()
        if stripped.lower().startswith("description:"):
            value = stripped.split(":", 1)[1].strip()
            return value == MDC_DESCRIPTION
    return False


def _install_one(root: Path, path: Path) -> AgentRow:
    label = _rel(root, path)
    existed = path.is_file()
    if not existed:
        newline = "\n"
        text = _mdc_for(newline) if _is_mdc(path) else _block_for(newline)
        write_bytes(path, _encode(b"", text))
        return AgentRow(path=label, status="created", written=True)

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return AgentRow(path=label, status="failed", detail=str(exc))
    try:
        bom, text = _decode(raw)
    except UnicodeDecodeError:
        return AgentRow(path=label, status="failed", detail="not UTF-8; fix by hand")

    newline = _newline(text)
    ended = text.endswith("\n")
    lines = _lines(text)

    if _is_mdc(path):
        canonical = _mdc_for(newline)
        if _encode(bom, canonical) == raw:
            return AgentRow(path=label, status="unchanged")
        if text.strip() and not _mdc_is_ours(text) and not any(BEGIN_RE.match(line.rstrip()) for line in lines):
            return AgentRow(
                path=label,
                status="failed",
                detail="not Costanza's .mdc; fix by hand",
            )
        write_bytes(path, _encode(bom, canonical))
        return AgentRow(path=label, status="installed", written=True)

    begins, ends = _marker_spans(lines)
    if not begins and not ends:
        block = _block_for(newline)
        stripped = text.rstrip("\r\n")
        if not stripped:
            new_text = block
        else:
            new_text = stripped + newline + newline + block
        write_bytes(path, _encode(bom, new_text))
        return AgentRow(path=label, status="installed", written=True)

    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        if len(begins) > 1:
            detail = f"{len(begins)} begin markers; fix by hand"
        elif not ends:
            detail = "begin marker without end; fix by hand"
        elif not begins:
            detail = "end marker without begin; fix by hand"
        else:
            detail = "end marker before begin; fix by hand"
        return AgentRow(path=label, status="failed", detail=detail)

    version = _begin_version(lines[begins[0]])
    if version is not None and version > AGENT_VERSION:
        return AgentRow(
            path=label,
            status="newer",
            detail=f"has a newer costanza block (v{version}); upgrade costanza",
        )

    block_lines = _lines(_block_for("\n").rstrip("\n"))
    new_lines = lines[: begins[0]] + block_lines + lines[ends[0] + 1 :]
    new_text = _join(new_lines, newline, ended=ended or True)
    new_bytes = _encode(bom, new_text)
    if new_bytes == raw:
        return AgentRow(path=label, status="unchanged")
    write_bytes(path, new_bytes)
    return AgentRow(path=label, status="installed", written=True)


def _remove_one(root: Path, path: Path) -> AgentRow:
    label = _rel(root, path)
    if not path.is_file():
        return AgentRow(path=label, status="missing")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return AgentRow(path=label, status="failed", detail=str(exc))
    try:
        bom, text = _decode(raw)
    except UnicodeDecodeError:
        return AgentRow(path=label, status="failed", detail="not UTF-8; fix by hand")

    newline = _newline(text)
    ended = text.endswith("\n")
    lines = _lines(text)

    if _is_mdc(path) and _mdc_is_ours(text):
        path.unlink()
        return AgentRow(path=label, status="deleted", written=True)

    begins, ends = _marker_spans(lines)
    if not begins and not ends:
        return AgentRow(path=label, status="unchanged")
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        return AgentRow(path=label, status="failed", detail="markers are not a single pair; fix by hand")

    drop_from = begins[0]
    if drop_from > 0 and lines[drop_from - 1].strip() == "":
        drop_from -= 1
    remaining = lines[:drop_from] + lines[ends[0] + 1 :]
    new_text = _join(remaining, newline, ended=ended)
    if not new_text.strip():
        path.unlink()
        return AgentRow(path=label, status="deleted", written=True)
    new_bytes = _encode(bom, new_text)
    if new_bytes == raw:
        return AgentRow(path=label, status="unchanged")
    write_bytes(path, new_bytes)
    return AgentRow(path=label, status="removed", written=True)


def _finish(rows: list[AgentRow]) -> AgentsResult:
    failed = any(row.status in {"failed", "newer"} for row in rows)
    return AgentsResult(rows=rows, failed=failed)


def install_agents(
    *,
    mode: str = "auto",
    targets: list[Path] | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> AgentsResult:
    root = discover_root(cwd, explicit, allow_cwd=True)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    chosen = select_targets(
        root,
        mode=mode,
        extra=targets,
        configured=() if targets else config.agents_targets,
    )
    rows = [_install_one(root, path) for path in chosen]
    if not rows:
        rows.append(AgentRow(path="(none)", status="unchanged", detail="no agent files selected"))
    return _finish(rows)


def remove_agents(
    *,
    mode: str = "auto",
    targets: list[Path] | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> AgentsResult:
    root = discover_root(cwd, explicit, allow_cwd=True)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    chosen = select_targets(
        root,
        mode=mode,
        extra=targets,
        configured=() if targets else config.agents_targets,
    )
    rows = [_remove_one(root, path) for path in chosen]
    if not rows:
        rows.append(AgentRow(path="(none)", status="unchanged", detail="no agent files selected"))
    return _finish(rows)


def status_agents(
    *,
    mode: str = "auto",
    targets: list[Path] | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> AgentsResult:
    root = discover_root(cwd, explicit, allow_cwd=True)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    chosen = select_targets(
        root,
        mode=mode,
        extra=targets,
        configured=() if targets else config.agents_targets,
    )
    rows: list[AgentRow] = []
    for path in chosen:
        label = _rel(root, path)
        if not path.is_file():
            rows.append(AgentRow(path=label, status="missing"))
            continue
        text = path.read_bytes()
        try:
            _, decoded = _decode(text)
        except UnicodeDecodeError:
            rows.append(AgentRow(path=label, status="failed", detail="not UTF-8"))
            continue
        lines = _lines(decoded)
        begins, ends = _marker_spans(lines)
        if len(begins) == 1 and len(ends) == 1 and ends[0] > begins[0]:
            version = _begin_version(lines[begins[0]])
            rows.append(AgentRow(path=label, status="installed", detail=f"v{version or '?'}"))
        elif not begins and not ends:
            rows.append(AgentRow(path=label, status="missing"))
        else:
            rows.append(AgentRow(path=label, status="failed", detail="markers are not a single pair"))
    return _finish(rows)
