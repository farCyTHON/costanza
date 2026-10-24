"""Build fixture git history in a temporary directory and export the final trees.

The export under bench/fixtures/ is the working tree only. This script never
writes a .git directory there, and it never changes git config.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.catalog import FIXTURES, Fixture, final_state, key_text  # noqa: E402


class BenchError(RuntimeError):
    """A fixture could not be built."""


def _git(dest: Path, base: list[str], args: list[str], env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(
        [*base, *args],
        cwd=dest,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise BenchError(f"git {' '.join(args)} failed: {detail}")


def build_repo(spec: Fixture, dest: Path) -> None:
    """Create ``dest`` as a new repository with this fixture's commits.

    ``dest`` must not already exist. The history is not copied into
    ``bench/fixtures``.
    """
    git = shutil.which("git")
    if git is None:
        raise BenchError("git is not on PATH")
    if dest.exists():
        raise BenchError(f"refusing to build into an existing directory: {dest}")
    dest.mkdir(parents=True)
    hooks = dest.parent / f".{spec.name}-hooks"
    hooks.mkdir(exist_ok=True)
    base = [
        git,
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.eol=lf",
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={hooks.as_posix()}",
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
    ]
    _git(dest, base, ["init", "-b", "main"])
    started = datetime(2026, 1, 6, 12, 0, 0, tzinfo=timezone.utc)
    for index, commit in enumerate(spec.commits):
        for rel, text in commit.files:
            path = dest / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        _git(dest, base, ["add", "-A"])
        when = (started + timedelta(days=index)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = "Fixture"
        env["GIT_AUTHOR_EMAIL"] = "fixture@example.invalid"
        env["GIT_COMMITTER_NAME"] = "Fixture"
        env["GIT_COMMITTER_EMAIL"] = "fixture@example.invalid"
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
        _git(dest, base, ["commit", "-m", commit.message], env)


def export_fixtures(root: Path | None = None) -> None:
    """Write final trees and answer keys. Does not create a git directory."""
    repo_root = root or ROOT
    fixtures = repo_root / "bench" / "fixtures"
    keys = repo_root / "bench" / "keys"
    for spec in FIXTURES:
        dest = fixtures / spec.name
        if dest.exists():
            shutil.rmtree(dest)
        for rel, text in final_state(spec).items():
            path = dest / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        if any(path.name == ".git" for path in dest.rglob("*")):
            raise BenchError(f"refusing to leave a git directory under {dest}")
        key = keys / f"{spec.name}.json"
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(key_text(spec), encoding="utf-8", newline="\n")


def main() -> None:
    export_fixtures()
    print("wrote bench/fixtures/till, bench/fixtures/slip, and bench/keys")


if __name__ == "__main__":
    try:
        main()
    except BenchError as exc:
        raise SystemExit(f"error: {exc}") from exc
