"""Post-commit hook. Records inbox fields only.

The hook never writes COSTANZA.md and never changes refs or the index.
A ``Costanza-Accept`` trailer sets ``suggested``. It does not accept.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from costanza.config import load_config
from costanza.exceptions import CostanzaError
from costanza.git import run_git
from costanza.inbox import Proposal, load_inbox, save_inbox, utc_now
from costanza.io import write_bytes
from costanza.lock import hold_lock
from costanza.paths import ProjectPaths, discover_root

_LOG_LIMIT = 32 * 1024
_GIT_TIMEOUT = 5.0
_MARKER = "# costanza-hook v"
_PID = re.compile(r"^p[1-9][0-9]*$")
_SHA = re.compile(r"^[0-9a-fA-F]{4,40}$")
_INSIDE = "hooks path is inside the repo; anyone who can commit can change your hooks"


@dataclass(frozen=True)
class HookReport:
    state: str
    message: str
    path: Path | None = None
    hint: str = ""
    warning: str = ""
    exit_code: int = 0
    log: str = ""


def render_script(python: str) -> str:
    """The section 8.1 script. ``python`` is stored with forward slashes."""
    py = python.replace("\\", "/")
    return (
        "#!/bin/sh\n"
        "# costanza-hook v1: managed by `cz hook`; `cz doctor` reports edits\n"
        '[ "$COSTANZA_HOOK" = "0" ] && exit 0\n'
        f"PY='{py}'\n"
        'if [ -x "$PY" ]; then\n'
        '  "$PY" -m costanza hook run post-commit\n'
        "elif command -v costanza >/dev/null 2>&1; then\n"
        "  costanza hook run post-commit\n"
        "fi\n"
        "exit 0\n"
    )


def install_hook(root: Path, *, python: str | None = None) -> HookReport:
    py = sys.executable if python is None else python
    if "'" in py:
        return HookReport(
            state="refused",
            message="Python path contains a single quote; install costanza in another location",
            hint="install costanza in another location",
            exit_code=1,
        )
    hooks = _hooks_directory(root)
    if hooks is None:
        return HookReport(
            state="refused",
            message="could not find the hooks directory",
            hint="git init and commit first",
            exit_code=1,
        )
    path = hooks / "post-commit"
    warning = _inside_repo_warning(root, hooks)
    expected = render_script(py).encode("utf-8")
    if path.exists() and not path.is_file():
        return _foreign(path, root, warning)
    existed = path.is_file()
    if existed:
        try:
            current = path.read_bytes()
        except OSError:
            return HookReport(
                state="refused",
                message=f"cannot read {_rel(root, path)}",
                path=path,
                hint="check the file permissions",
                warning=warning,
                exit_code=1,
            )
        if not _ours(current):
            return _foreign(path, root, warning)
        if current == expected:
            return HookReport(
                state="unchanged",
                message="post-commit unchanged",
                path=path,
                warning=warning,
            )
    hooks.mkdir(parents=True, exist_ok=True)
    write_bytes(path, expected)
    if os.name != "nt":
        os.chmod(path, 0o755)
    if existed:
        return HookReport(state="updated", message="post-commit updated", path=path, warning=warning)
    return HookReport(state="installed", message="post-commit installed", path=path, warning=warning)


def remove_hook(root: Path) -> HookReport:
    hooks = _hooks_directory(root)
    if hooks is None:
        return HookReport(state="missing", message="missing")
    path = hooks / "post-commit"
    if not path.exists():
        return HookReport(state="missing", message="missing", path=path)
    if not path.is_file():
        return _foreign(path, root, "")
    try:
        current = path.read_bytes()
    except OSError:
        return HookReport(
            state="refused",
            message=f"cannot read {_rel(root, path)}",
            path=path,
            hint="check the file permissions",
            exit_code=1,
        )
    if not _ours(current):
        return _foreign(path, root, "")
    if _classify(current) != "installed":
        return HookReport(
            state="modified",
            message=f"{_rel(root, path)} was edited; remove it by hand",
            path=path,
            hint="delete the file yourself, then cz hook install",
            exit_code=1,
        )
    path.unlink()
    return HookReport(state="removed", message="post-commit removed", path=path)


def hook_status(root: Path) -> HookReport:
    hooks = _hooks_directory(root)
    log = _log_section(root)
    if hooks is None:
        return HookReport(state="missing", message="missing", log=log)
    path = hooks / "post-commit"
    if not path.is_file():
        return HookReport(state="missing", message="missing", path=path, log=log)
    try:
        current = path.read_bytes()
    except OSError:
        return HookReport(state="missing", message="missing", path=path, log=log)
    state = "foreign" if not _ours(current) else _classify(current)
    return HookReport(state=state, message=state, path=path, log=log)


def run_post_commit(
    event: str,
    *,
    explicit: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """Apply the latest commit to the inbox. Always safe for the caller to ignore."""
    if os.environ.get("COSTANZA_HOOK") == "0":
        return ""
    if event.strip() != "post-commit":
        return "costanza: hook skipped: unknown event"
    try:
        root = discover_root(cwd=cwd, explicit=explicit)
    except CostanzaError as exc:
        return f"costanza: hook skipped: {exc.message}"
    paths = ProjectPaths(root)
    try:
        return _apply_head(paths)
    except CostanzaError as exc:
        append_hook_log(paths.hook_log, exc.message)
        return f"costanza: hook skipped: {exc.message}"
    except Exception as exc:
        append_hook_log(paths.hook_log, f"{type(exc).__name__}: {exc}")
        return f"costanza: hook skipped: {type(exc).__name__}: {exc}"


def landing_sha(
    root: Path,
    item: Proposal,
    cache: dict[str, set[str] | None] | None = None,
) -> str | None:
    """Short sha when this proposal's files overlap that commit, else None."""
    sha = item.commit
    if not sha or not item.files or not _SHA.fullmatch(sha):
        return None
    if not (root / ".git").exists():
        return None
    if cache is not None and sha in cache:
        names = cache[sha]
    else:
        names = _commit_files(root, sha)
        if cache is not None:
            cache[sha] = names
    if not names:
        return None
    wanted = {_norm(name) for name in item.files}
    if wanted & names:
        return sha
    return None


def append_hook_log(path: Path, reason: str) -> None:
    """Append one short line, rotating to hook.log.1 at 32 KiB. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size >= _LOG_LIMIT:
            backup = path.with_name(f"{path.name}.1")
            try:
                backup.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                path.replace(backup)
            except OSError:
                pass
        first = reason.replace("\r", " ").replace("\n", " ").strip() or "unknown problem"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{utc_now()} {first[:240]}\n")
    except OSError:
        return


def _log_section(root: Path) -> str:
    path = ProjectPaths(root).hook_log
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-8:])


def _apply_head(paths: ProjectPaths) -> str:
    head = _read_head(paths.root)
    if head is None:
        append_hook_log(paths.hook_log, "could not read HEAD")
        return "costanza: hook skipped: could not read HEAD"
    sha, author, trailers = head
    try:
        config = load_config(paths.config)
    except CostanzaError as exc:
        append_hook_log(paths.hook_log, exc.message)
        return f"costanza: hook skipped: {exc.message}"
    handoff = paths.file
    before = handoff.read_bytes() if handoff.is_file() else None
    accept, reject = _trailer_ids(trailers) if config.apply_trailers else ([], [])
    with hold_lock(paths):
        inbox = load_inbox(paths.inbox)
        changed, message, notices = _mutate(
            inbox.proposals(), sha, author, accept, reject, config.stamp_commits
        )
        if changed:
            save_inbox(paths, inbox)
    for note in notices:
        append_hook_log(paths.hook_log, note)
    after = handoff.read_bytes() if handoff.is_file() else None
    if before != after:
        note = "costanza: COSTANZA.md changed; include it in the next commit"
        message = f"{message}\n{note}" if message else note
    return message


def _mutate(
    proposals: list[Proposal],
    sha: str,
    author: datetime,
    accept: list[str],
    reject: list[str],
    stamp: bool,
) -> tuple[bool, str, list[str]]:
    by_id = {item.id: item for item in proposals}
    stamped: list[str] = []
    suggested: list[str] = []
    rejected: list[str] = []
    notices: list[str] = []
    changed = False
    if stamp:
        for item in proposals:
            if item.commit is not None or not _eligible(item, author):
                continue
            item.commit = sha
            stamped.append(item.id)
            changed = True
    for pid in accept:
        chosen = by_id.get(pid)
        if chosen is None:
            notices.append(f"{pid} unknown")
            continue
        if chosen.status == "dismissed":
            notices.append(f"{pid} dismissed")
            continue
        if chosen.status == "accepted":
            notices.append(f"{pid} accepted")
            continue
        if not _eligible(chosen, author) or chosen.suggested:
            continue
        chosen.suggested = sha
        suggested.append(pid)
        changed = True
    now = utc_now()
    for pid in reject:
        chosen = by_id.get(pid)
        if chosen is None or not _eligible(chosen, author):
            continue
        chosen.status = "rejected"
        chosen.decided = now
        chosen.via = "trailer"
        rejected.append(pid)
        changed = True
    return changed, _join_summary(_summary(stamped, suggested, rejected, sha), notices), notices


def _summary(stamped: list[str], suggested: list[str], rejected: list[str], sha: str) -> str:
    parts: list[str] = []
    if stamped:
        parts.append(f"{', '.join(stamped)} stamped {sha}")
    if suggested:
        parts.append(f"{', '.join(suggested)} suggested for review")
    if rejected:
        parts.append(f"{', '.join(rejected)} rejected")
    if not parts:
        return ""
    text = "costanza: " + "; ".join(parts)
    if suggested or rejected:
        text += "; next: cz review"
    return text


def _join_summary(summary: str, notices: list[str]) -> str:
    if not notices:
        return summary
    skip = "; ".join(notices) + "; not changed"
    marker = "; next: cz review"
    if not summary:
        return "costanza: " + skip
    if summary.endswith(marker):
        return summary[: -len(marker)] + "; " + skip + marker
    return summary + "; " + skip


def _eligible(item: Proposal, author: datetime) -> bool:
    if item.status != "proposed":
        return False
    return not _newer_than_commit(item.ts, author)


def _newer_than_commit(ts: str, author: datetime) -> bool:
    if not ts:
        return False
    parsed = _parse_time(ts)
    if parsed is None:
        return True
    return parsed > author


def _trailer_ids(trailers: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    accept: list[str] = []
    reject: list[str] = []
    for key, value in trailers:
        folded = key.casefold()
        if folded == "costanza-accept":
            _extend_unique(accept, _pids(value))
        elif folded == "costanza-reject":
            _extend_unique(reject, _pids(value))
    return accept, reject


def _pids(value: str) -> list[str]:
    found: list[str] = []
    for part in value.split(","):
        token = part.strip()
        if _PID.fullmatch(token):
            found.append(token)
    return found


def _extend_unique(target: list[str], extra: list[str]) -> None:
    for pid in extra:
        if pid not in target:
            target.append(pid)


def _read_head(root: Path) -> tuple[str, datetime, list[tuple[str, str]]] | None:
    """One git call. ``%(trailers)`` is git's own trailer parser."""
    result = run_git(
        root,
        ["log", "-1", "--format=%h%x00%aI%x00%(trailers:only,unfold)"],
        timeout=_GIT_TIMEOUT,
    )
    if not result.ok:
        return None
    raw = result.stdout.replace("\r\n", "\n").replace("\r", "\n")
    parts = raw.split("\x00")
    if len(parts) < 3:
        return None
    sha = parts[0].strip()
    author = _parse_time(parts[1].strip())
    if author is None or not _SHA.fullmatch(sha):
        return None
    return sha, author, _parse_trailers("\x00".join(parts[2:]))


def _parse_trailers(blob: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in blob.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            found.append((key, value.strip()))
    return found


def _parse_time(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _commit_files(root: Path, sha: str) -> set[str] | None:
    result = run_git(
        root,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", sha],
        timeout=_GIT_TIMEOUT,
    )
    if not result.ok:
        return None
    return {_norm(line) for line in result.stdout.splitlines() if line.strip()}


def _norm(path: str) -> str:
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def _hooks_directory(root: Path) -> Path | None:
    result = run_git(root, ["rev-parse", "--git-path", "hooks"], timeout=_GIT_TIMEOUT)
    if not result.ok:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path


def _inside_repo_warning(root: Path, hooks: Path) -> str:
    try:
        resolved = hooks.resolve()
        root_r = root.resolve()
    except OSError:
        return ""
    if not _is_inside(resolved, root_r):
        return ""
    git_dir = root / ".git"
    if git_dir.is_dir():
        try:
            if _is_inside(resolved, git_dir.resolve()):
                return ""
        except OSError:
            return ""
    return _INSIDE


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _ours(data: bytes) -> bool:
    lines = data.decode("utf-8", errors="replace").splitlines()
    return len(lines) >= 2 and lines[1].startswith(_MARKER)


def _python_line(data: bytes) -> str | None:
    for line in data.decode("utf-8", errors="replace").splitlines():
        if line.startswith("PY='") and line.endswith("'") and len(line) >= 5:
            return line[4:-1]
    return None


def _classify(data: bytes) -> str:
    """``installed`` when the bytes match the script for the PY it names."""
    py = _python_line(data)
    if py is None:
        return "modified"
    if data == render_script(py).encode("utf-8"):
        return "installed"
    return "modified"


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _foreign(path: Path, root: Path, warning: str) -> HookReport:
    return HookReport(
        state="foreign",
        message=f"{_rel(root, path)} exists and is not Costanza's",
        path=path,
        hint="add this line to it: costanza hook run post-commit || true",
        warning=warning,
        exit_code=1,
    )
