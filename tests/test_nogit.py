from __future__ import annotations

import subprocess
from pathlib import Path

from costanza.constants import NEED_GIT_COMMIT
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--agents", "none"])
    assert result.exit_code == 0, result.output


def test_status_says_no_git_and_does_not_suggest_sync(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "status"])
    assert result.exit_code == 0, result.output
    assert "no git" in result.stdout
    assert "synced never" not in result.stdout
    assert "cz sync" not in result.stdout + result.stderr


def test_check_skips_staleness_without_git(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0, result.output
    assert "W107" not in result.output
    assert "W108" not in result.output


def test_sync_and_hook_without_git_are_one_line(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    for args in (["sync"], ["hook", "install"]):
        result = invoke(["--root", str(tmp_path), *args])
        assert result.exit_code == 2, result.output
        assert result.stderr.strip() == NEED_GIT_COMMIT
        assert "Traceback" not in result.output


def test_everyday_commands_work_without_git(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    scan = invoke(["--root", str(tmp_path), "scan"])
    assert scan.exit_code == 0, scan.output
    handoff = invoke(["--root", str(tmp_path), "handoff"])
    assert handoff.exit_code == 0, handoff.output
    assert "# PROJECT:" in handoff.stdout
    compact = invoke(["--root", str(tmp_path), "compact"])
    assert compact.exit_code == 0, compact.output
    now = invoke(["--root", str(tmp_path), "now", "--doing", "local only"])
    assert now.exit_code == 0, now.output
    agents = invoke(["--root", str(tmp_path), "agents", "status"])
    assert agents.exit_code == 0, agents.output
    pasted = invoke(
        ["--root", str(tmp_path), "paste"],
        input="```costanza\nrule: stay local\n```\n",
    )
    assert pasted.exit_code == 0, pasted.output
    review = invoke(["--root", str(tmp_path), "review"])
    assert review.exit_code == 2
    assert "interactive terminal" in review.stderr
    assert "Traceback" not in review.output


def test_empty_git_repo_matches_no_commit_message(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    status = invoke(["--root", str(git_repo), "status"])
    assert status.exit_code == 0, status.output
    assert "synced never" in status.stdout
    assert "cz sync" not in status.stdout + status.stderr
    checked = invoke(["--root", str(git_repo), "check"])
    assert "W107" not in checked.output
    assert "W108" not in checked.output
    for args in (["sync"], ["hook", "install"]):
        result = invoke(["--root", str(git_repo), *args])
        assert result.exit_code == 2, result.output
        assert result.stderr.strip() == NEED_GIT_COMMIT
        assert "Traceback" not in result.output


def test_hook_install_works_after_a_commit(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    note = git_repo / "note.txt"
    note.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "note"], cwd=git_repo, check=True, capture_output=True)
    result = invoke(["--root", str(git_repo), "hook", "install"])
    assert result.exit_code == 0, result.output
    script = (git_repo / ".git" / "hooks" / "post-commit").read_bytes()
    assert b"\r" not in script
    assert script.startswith(b"#!/bin/sh\n")
    assert b"# costanza-hook v" in script
