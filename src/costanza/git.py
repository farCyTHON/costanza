"""One git adapter. Command line only, same behaviour on Windows.

Never uses the shell. Missing git and a non-repo root are ordinary
results, not crashes. Callers that need git (sync) raise GitError.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from costanza.exceptions import GitError

_TIMEOUT = 30


@dataclass(frozen=True)
class GitRun:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0


@dataclass(frozen=True)
class GitProbe:
    available: bool
    repo: bool
    detail: str = ""


def git_executable() -> str | None:
    return shutil.which("git")


def run_git(root: Path, args: list[str], timeout: float | None = None) -> GitRun:
    """Run ``git <args>`` in ``root``. Does not raise on a non-zero exit."""
    exe = git_executable()
    if exe is None:
        return GitRun(code=127, stdout="", stderr="git not found on PATH")
    try:
        proc = subprocess.run(
            [exe, "-c", "core.quotepath=off", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT if timeout is None else timeout,
            check=False,
        )
    except FileNotFoundError:
        return GitRun(code=127, stdout="", stderr="git not found on PATH")
    except subprocess.TimeoutExpired:
        return GitRun(code=124, stdout="", stderr="git timed out")
    return GitRun(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def probe(root: Path) -> GitProbe:
    if git_executable() is None:
        return GitProbe(available=False, repo=False, detail="git not found on PATH")
    result = run_git(root, ["rev-parse", "--show-toplevel"])
    if result.code == 127:
        return GitProbe(available=False, repo=False, detail="git not found on PATH")
    if not result.ok:
        return GitProbe(available=True, repo=False, detail="not a git repository")
    try:
        top = Path(result.stdout.strip()).resolve()
    except OSError:
        return GitProbe(available=True, repo=False, detail="not a git repository")
    if top != root.resolve():
        # A parent repo must not count. Costanza only sees a repo at this root.
        return GitProbe(available=True, repo=False, detail="not a git repository")
    return GitProbe(available=True, repo=True)


def git_gap(root: Path) -> str | None:
    """Return the one-line usage message when git cannot record a commit."""
    from costanza.constants import NEED_GIT_COMMIT

    info = probe(root)
    if not info.available or not info.repo or not has_commits(root):
        return NEED_GIT_COMMIT
    return None


def require_repo(root: Path) -> None:
    info = probe(root)
    if not info.available:
        raise GitError("git not found on PATH", "install git")
    if not info.repo:
        raise GitError("not a git repository", "git init and commit first")


def ls_files(root: Path) -> list[str] | None:
    """Repo-relative POSIX paths, or None if git cannot list them."""
    info = probe(root)
    if not info.available or not info.repo:
        return None
    result = run_git(root, ["ls-files", "-z"])
    if not result.ok:
        return None
    return [item.replace("\\", "/") for item in result.stdout.split("\0") if item]


def head(root: Path) -> tuple[str, str]:
    """Return ``(short_sha, YYYY-MM-DD)`` for HEAD (committer date, UTC)."""
    require_repo(root)
    result = run_git(root, ["log", "-1", "--format=%h%x00%cI"])
    if not result.ok or not result.stdout.strip():
        raise GitError("no commits in this repository", "git init and commit first")
    raw = result.stdout.strip("\n")
    if "\x00" not in raw:
        raise GitError("could not read HEAD", "git log -1")
    sha, iso = raw.split("\x00", 1)
    sha = sha.strip()
    date = iso.strip()[:10]
    if not sha or len(date) != 10:
        raise GitError("could not read HEAD", "git log -1")
    return sha, date


def commit_exists(root: Path, sha: str) -> bool:
    result = run_git(root, ["cat-file", "-t", sha])
    return result.ok and result.stdout.strip() == "commit"


def commits_behind(root: Path, sha: str) -> int | None:
    """Commits on HEAD that are not ancestors of ``sha``, or None if unknown."""
    if not commit_exists(root, sha):
        return None
    result = run_git(root, ["rev-list", "--count", f"{sha}..HEAD"])
    if not result.ok:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def has_commits(root: Path) -> bool:
    result = run_git(root, ["rev-parse", "--verify", "HEAD"])
    return result.ok


def diff_names(root: Path, old: str) -> list[str] | None:
    """Paths changed between ``old`` and HEAD, or None if ``old`` is unknown."""
    if not commit_exists(root, old):
        return None
    result = run_git(root, ["diff", "--name-only", f"{old}..HEAD"])
    if not result.ok:
        return None
    return [line.replace("\\", "/").strip() for line in result.stdout.splitlines() if line.strip()]
