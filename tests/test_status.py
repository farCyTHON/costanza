from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import InvokeFn, InvokeResult


def _write_file(root: Path, text: str) -> None:
    (root / "COSTANZA.md").write_text(text, encoding="utf-8", newline="\n")


def test_status_missing(invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result: InvokeResult = invoke(["status"])
    assert result.exit_code == 1
    assert "next: cz init" in result.stderr


def test_status_tiny_tokens_and_snapshot(
    invoke: InvokeFn, tmp_path: Path, tiny_text: str
) -> None:
    _write_file(tmp_path, tiny_text)
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"])
    assert result.exit_code == 0, result.output
    assert "~238 / 1,800" in result.stdout
    assert "13%" in result.stdout
    assert "D 2" in result.stdout
    assert "inbox  0 proposed" in result.stdout
    assert "payment webhook retries" in result.stdout
    assert "synced a1b2c3d 2026-10-12" in result.stdout


def test_status_near_warn(invoke: InvokeFn, tmp_path: Path, near_text: str) -> None:
    _write_file(tmp_path, near_text)
    inbox = tmp_path / ".costanza"
    inbox.mkdir()
    lines = [
        '{"status":"proposed","id":"p1"}',
        '{"status":"proposed","id":"p2"}',
        '{"status":"proposed","id":"p3"}',
        '{"status":"accepted","id":"p0"}',
    ]
    (inbox / "inbox.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"])
    assert result.exit_code == 0
    assert "~1,666 / 1,800" in result.stdout
    assert "93%" in result.stdout
    assert "inbox  3 proposed" in result.stdout
    assert "near budget (93%)" in result.stderr
    assert "cz review (3 proposals waiting)" in result.stdout


def test_status_json_tiny(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write_file(tmp_path, tiny_text)
    result: InvokeResult = invoke(["--root", str(tmp_path), "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    expected = {
        "project": "shopbot, Telegram order bot",
        "tokens": 238,
        "budget": 1800,
        "ratio": 0.132,
        "state": "ok",
        "estimator": "estimate",
        "counts": {"D": 2, "X": 1, "R": 1, "G": 1, "Q": 1},
        "inbox": {"proposed": 0},
        "now": {
            "doing": "payment webhook retries (app/services/pay.py)",
            "done": "auth, cart, order model",
            "next": "backoff, admin export",
            "blocked": "none",
        },
        "header": {
            "stack": "python3.12, FastAPI, SQLite, pytest",
            "run": "uvicorn app.main:app",
            "test": "pytest -q",
            "layout": "app/routes (HTTP), app/services (logic), app/db (queries)",
        },
        "synced": {"sha": "a1b2c3d", "date": "2026-10-12"},
        "behind": None,
        "problems": [],
    }
    data.pop("root")
    assert data == expected


def test_status_one_problem(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    text = tiny_text.replace("blocked: none\n", "blocked: none\nthis is not an entry\n")
    _write_file(tmp_path, text)
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"])
    assert result.exit_code == 0
    assert "1 problem; next: cz check" in result.stderr


def test_status_unreadable_marker(invoke: InvokeFn, tmp_path: Path) -> None:
    _write_file(tmp_path, "# not a costanza file\n")
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"])
    assert result.exit_code == 1
    assert "line 1" in result.stderr


def test_quiet_status(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write_file(tmp_path, tiny_text)
    result: InvokeResult = invoke(["--quiet", "--root", str(tmp_path), "status"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "shopbot  238/1,800 (13%)  0 proposed"


def test_status_shows_behind_head(invoke: InvokeFn, git_repo: Path) -> None:
    import subprocess

    invoke(["--root", str(git_repo), "init"])
    first = None
    for index in range(3):
        path = git_repo / f"n{index}.txt"
        path.write_text(f"{index}\n", encoding="utf-8")
        subprocess.run(["git", "add", f"n{index}.txt"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", str(index)], cwd=git_repo, check=True, capture_output=True)
        if first is None:
            first = subprocess.check_output(
                ["git", "log", "-1", "--format=%h"], cwd=git_repo, text=True
            ).strip()
    text = (git_repo / "COSTANZA.md").read_text(encoding="utf-8")
    (git_repo / "COSTANZA.md").write_text(
        text.replace("synced: never", f"synced: {first} 2026-01-01"),
        encoding="utf-8",
    )
    result = invoke(["--root", str(git_repo), "status"])
    assert result.exit_code == 0, result.output
    assert f"synced {first} 2026-01-01" in result.stdout
    assert "2 behind" in result.stdout
    drifted = invoke(["--root", str(git_repo), "status", "--json"])
    drifted_data = json.loads(drifted.stdout)
    assert drifted_data["synced"] == {"sha": first, "date": "2026-01-01"}
    assert drifted_data["behind"] == 2
    head = subprocess.check_output(
        ["git", "log", "-1", "--format=%h"], cwd=git_repo, text=True
    ).strip()
    (git_repo / "COSTANZA.md").write_text(
        (git_repo / "COSTANZA.md")
        .read_text(encoding="utf-8")
        .replace(f"synced: {first} 2026-01-01", f"synced: {head} 2026-01-01"),
        encoding="utf-8",
    )
    synced = invoke(["--root", str(git_repo), "status"])
    assert synced.exit_code == 0, synced.output
    assert f"synced {head} 2026-01-01" in synced.stdout
    assert "0 behind" in synced.stdout
    payload = invoke(["--root", str(git_repo), "status", "--json"])
    data = json.loads(payload.stdout)
    assert data["synced"] == {"sha": head, "date": "2026-01-01"}
    assert data["behind"] == 0


def test_status_json_behind_null_when_never_or_not_git(
    invoke: InvokeFn, git_repo: Path, tmp_path: Path, tiny_text: str
) -> None:
    invoke(["--root", str(git_repo), "init"])
    never = invoke(["--root", str(git_repo), "status", "--json"])
    assert never.exit_code == 0, never.output
    never_data = json.loads(never.stdout)
    assert never_data["synced"] is None
    assert never_data["behind"] is None

    _write_file(tmp_path, tiny_text)
    outside = invoke(["--root", str(tmp_path), "status", "--json"])
    assert outside.exit_code == 0, outside.output
    outside_data = json.loads(outside.stdout)
    assert outside_data["synced"] == {"sha": "a1b2c3d", "date": "2026-10-12"}
    assert outside_data["behind"] is None


def test_status_skeleton_next(invoke: InvokeFn, tmp_path: Path) -> None:
    from costanza.constants import skeleton

    _write_file(tmp_path, skeleton("demo"))
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"])
    assert result.exit_code == 0
    assert "edit the header in COSTANZA.md" in result.stdout
