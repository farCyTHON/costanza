from __future__ import annotations

import subprocess
from pathlib import Path

from tests.helpers import InvokeFn


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, name: str, content: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


def test_sync_requires_git(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init", "--agents", "none"])
    result = invoke(["--root", str(tmp_path), "sync"])
    assert result.exit_code == 2
    assert result.stderr.strip() == (
        "needs a git repo with at least one commit (git init is enough, no remote needed)"
    )
    assert "Traceback" not in result.stderr


def test_sync_sets_head_after_confirm(invoke: InvokeFn, git_repo: Path, monkeypatch: object) -> None:
    monkeypatch.setattr("costanza.ui.ask_yes_no", lambda _msg: True)
    invoke(["--root", str(git_repo), "init"])
    _commit(git_repo, "app.py", "print(1)\n")
    dry = invoke(["--root", str(git_repo), "sync", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "would set synced" in dry.stdout
    text = (git_repo / "COSTANZA.md").read_text(encoding="utf-8")
    assert "synced: never" in text
    applied = invoke(["--root", str(git_repo), "sync"])
    assert applied.exit_code == 0, applied.output
    assert "synced" in applied.stdout
    updated = (git_repo / "COSTANZA.md").read_text(encoding="utf-8")
    assert "synced: never" not in updated
    sha = subprocess.check_output(
        ["git", "log", "-1", "--format=%h"], cwd=git_repo, text=True
    ).strip()
    assert sha in updated


def test_sync_reports_changed_and_missing_files(
    invoke: InvokeFn, git_repo: Path, monkeypatch: object
) -> None:
    from costanza.constants import MARKER_CANONICAL

    monkeypatch.setattr("costanza.ui.ask_yes_no", lambda _msg: True)
    _commit(git_repo, "app/db/conn.py", "x = 1\n")
    first = subprocess.check_output(
        ["git", "log", "-1", "--format=%h"], cwd=git_repo, text=True
    ).strip()
    body = (
        f"{MARKER_CANONICAL}\n"
        "# PROJECT: shop\n"
        "stack: python\n"
        "run: x | test: x\n"
        "layout: app/\n"
        f"synced: {first} 2026-10-01\n"
        "\n"
        "## NOW\n"
        "doing: none\n"
        "done: none\n"
        "next: none\n"
        "blocked: none\n"
        "\n"
        "## DECISIONS\n"
        "D1 keep sqlite [files: app/db/conn.py]\n"
        "\n"
        "## REJECTED\n"
        "\n"
        "## RULES\n"
        "\n"
        "## GOTCHAS\n"
        "G1 vanished path [files: app/bot/router.py]\n"
        "\n"
        "## OPEN\n"
    )
    (git_repo / "COSTANZA.md").write_text(body, encoding="utf-8")
    _commit(git_repo, "app/db/conn.py", "x = 2\n")
    result = invoke(["--root", str(git_repo), "sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "D1" in result.stderr
    assert "conn.py" in result.stderr
    assert "G1" in result.stderr
    assert "no longer exists" in result.stderr
