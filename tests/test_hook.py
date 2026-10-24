"""Post-commit hook, trailers and landing stamps."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from costanza.hooks import install_hook, landing_sha, render_script, run_post_commit
from costanza.inbox import Proposal, load_inbox, save_inbox
from costanza.paths import ProjectPaths
from costanza.ui import configure, render_review_card
from tests.helpers import InvokeFn

_MESSAGE = """ship the hook
Costanza-Accept: p4

sekret-token-should-not-log

costanza-accept: nope, p1, p2, p99, p5
Costanza-Accept: p2
Costanza-Reject: p3, bad
Broken: not-a-trailer
"""


def _init(invoke: InvokeFn, repo: Path) -> None:
    result = invoke(["--root", str(repo), "init", "--agents", "none"])
    assert result.exit_code == 0, result.output


def _git(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _seed(repo: Path) -> None:
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")


def _short_head(repo: Path) -> str:
    return _git(repo, "log", "-1", "--format=%h").stdout.strip()


def _count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD").stdout.strip())


def _propose(invoke: InvokeFn, repo: Path, text: str, files: str | None = None) -> None:
    args = ["--root", str(repo), "decide", text]
    if files:
        args.extend(["--files", files])
    result = invoke(args)
    assert result.exit_code == 0, result.output


def test_script_quotes_unusual_python_paths() -> None:
    path = "C:/Program Files/costanza $HOME & (x) `y` ünï Ж/python.exe"
    text = render_script(path)
    assert f"PY='{path}'" in text
    assert "\r" not in text
    assert "\n" in text
    assert text.splitlines()[1].startswith("# costanza-hook v")


def test_python_path_with_a_quote_is_refused(tmp_path: Path) -> None:
    report = install_hook(tmp_path, python="C:/it's/python.exe")
    assert report.exit_code == 1
    assert "single quote" in report.message
    assert list(tmp_path.iterdir()) == []


def test_install_status_reinstall_and_uninstall(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    first = invoke(["--root", str(git_repo), "hook", "install"])
    assert first.exit_code == 0, first.output
    assert "post-commit installed" in first.stdout
    script = git_repo / ".git" / "hooks" / "post-commit"
    data = script.read_bytes()
    assert b"\r" not in data
    assert data == render_script(sys.executable).encode("utf-8")
    if os.name != "nt":
        assert (script.stat().st_mode & 0o777) == 0o755
    status = invoke(["--root", str(git_repo), "hook", "status"])
    assert status.exit_code == 0, status.output
    assert status.stdout.splitlines()[0] == "installed"
    assert "log" in status.stdout
    stamp = script.stat().st_mtime_ns
    again = invoke(["--root", str(git_repo), "hook", "install"])
    assert again.exit_code == 0, again.output
    assert "unchanged" in again.stdout
    assert script.stat().st_mtime_ns == stamp
    assert script.read_bytes() == data
    removed = invoke(["--root", str(git_repo), "hook", "uninstall"])
    assert removed.exit_code == 0, removed.output
    assert "removed" in removed.stdout
    assert not script.exists()
    missing = invoke(["--root", str(git_repo), "hook", "status"])
    assert missing.stdout.splitlines()[0] == "missing"
    assert "log" in missing.stdout


def test_install_refuses_a_foreign_hook(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    original = b"#!/bin/sh\necho kept\n"
    hook.write_bytes(original)
    result = invoke(["--root", str(git_repo), "hook", "install"])
    assert result.exit_code == 1, result.output
    assert "not Costanza's" in result.stderr
    assert "costanza hook run post-commit || true" in result.output
    assert hook.read_bytes() == original
    status = invoke(["--root", str(git_repo), "hook", "status"])
    assert status.stdout.splitlines()[0] == "foreign"
    assert "log" in status.stdout
    removed = invoke(["--root", str(git_repo), "hook", "uninstall"])
    assert removed.exit_code == 1, removed.output
    assert hook.read_bytes() == original


def test_modified_hook_is_reported_and_remove_refuses(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    invoke(["--root", str(git_repo), "hook", "install"])
    script = git_repo / ".git" / "hooks" / "post-commit"
    original = script.read_bytes()
    edited = bytearray(original)
    edited[-2] = ord("9")
    script.write_bytes(bytes(edited))
    status = invoke(["--root", str(git_repo), "hook", "status"])
    assert status.stdout.splitlines()[0] == "modified"
    assert "log" in status.stdout
    removed = invoke(["--root", str(git_repo), "hook", "remove"])
    assert removed.exit_code == 1, removed.output
    assert "remove it by hand" in removed.stderr
    assert script.read_bytes() == bytes(edited)


def test_hooks_path_with_a_space(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    _git(git_repo, "config", "core.hooksPath", "my hooks")
    result = invoke(["--root", str(git_repo), "hook", "install"])
    assert result.exit_code == 0, result.output
    script = git_repo / "my hooks" / "post-commit"
    assert script.is_file()
    assert b"\r" not in script.read_bytes()
    assert "hooks path is inside the repo" in result.stderr
    assert not (git_repo / ".git" / "hooks" / "post-commit").exists()


def test_trailers_stamp_and_a_second_run_is_a_no_op(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    _propose(invoke, git_repo, "future idea")
    _propose(invoke, git_repo, "suggest me", "other.py")
    _propose(invoke, git_repo, "reject me")
    _propose(invoke, git_repo, "landed work", "nested/pay.py")
    _propose(invoke, git_repo, "already closed")
    dismissed = invoke(["--root", str(git_repo), "dismiss", "p5"])
    assert dismissed.exit_code == 0, dismissed.output
    inbox = load_inbox(git_repo / ".costanza" / "inbox.jsonl")
    future = inbox.by_id("p1")
    assert future is not None
    future.ts = "2099-01-01T00:00:00Z"
    save_inbox(ProjectPaths(git_repo), inbox)
    nested = git_repo / "nested"
    nested.mkdir()
    pay = nested / "pay.py"
    pay.write_text("pay\n", encoding="utf-8")
    _git(git_repo, "add", "--", "nested/pay.py")
    msg = git_repo.parent / "commit-msg.txt"
    msg.write_bytes(_MESSAGE.encode("utf-8"))
    handoff = (git_repo / "COSTANZA.md").read_bytes()
    before = _count(git_repo)
    _git(git_repo, "commit", "-q", "-F", str(msg), cwd=nested)
    assert _count(git_repo) == before + 1
    sha = _short_head(git_repo)
    first = run_post_commit("post-commit", cwd=nested)
    assert "hook skipped" not in first, first
    assert "suggested for review" in first
    assert "p3 rejected" in first
    assert "next: cz review" in first
    assert "COSTANZA.md changed" not in first
    assert (git_repo / "COSTANZA.md").read_bytes() == handoff
    assert _count(git_repo) == before + 1
    loaded = load_inbox(git_repo / ".costanza" / "inbox.jsonl")
    p1 = loaded.by_id("p1")
    p2 = loaded.by_id("p2")
    p3 = loaded.by_id("p3")
    p4 = loaded.by_id("p4")
    p5 = loaded.by_id("p5")
    assert p1 is not None and p1.status == "proposed" and p1.suggested is None and p1.commit is None
    assert p2 is not None and p2.status == "proposed" and p2.suggested == sha and p2.commit == sha
    assert p3 is not None and p3.status == "rejected" and p3.via == "trailer" and p3.commit == sha
    assert p4 is not None and p4.status == "proposed" and p4.suggested is None and p4.commit == sha
    assert p5 is not None and p5.status == "dismissed" and p5.suggested is None
    log = git_repo / ".costanza" / "hook.log"
    logged = log.read_text(encoding="utf-8")
    assert "sekret-token-should-not-log" not in logged
    assert "p99 unknown" in logged
    assert "p5 dismissed" in logged
    status = invoke(["--root", str(git_repo), "hook", "status"])
    assert status.exit_code == 0, status.output
    assert "log" in status.stdout
    assert "p99 unknown" in status.stdout
    assert landing_sha(git_repo, p4) == sha
    assert landing_sha(git_repo, p2) is None
    blob = (git_repo / ".costanza" / "inbox.jsonl").read_bytes()
    started = time.perf_counter()
    second = run_post_commit("post-commit", explicit=git_repo)
    elapsed = time.perf_counter() - started
    assert "p99 unknown" in second
    assert "p5 dismissed" in second
    assert "not changed" in second
    assert (git_repo / ".costanza" / "inbox.jsonl").read_bytes() == blob
    assert elapsed < 2.0, f"second hook run took {elapsed:.3f}s"
    skipped = invoke(["--root", str(git_repo), "hook", "run", "nope"])
    assert skipped.exit_code == 0, skipped.output
    assert "unknown event" in skipped.stderr


def test_installed_hook_runs_for_a_subdirectory_commit(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    installed = invoke(["--root", str(git_repo), "hook", "install"])
    assert installed.exit_code == 0, installed.output
    _propose(invoke, git_repo, "from the hook", "nested/pay.py")
    nested = git_repo / "nested"
    nested.mkdir()
    (nested / "pay.py").write_text("pay\n", encoding="utf-8")
    _git(git_repo, "add", "--", "nested/pay.py")
    msg = git_repo.parent / "hook-msg.txt"
    msg.write_bytes(b"pay\n\nCostanza-Accept: p1\nCostanza-Reject: nope\n")
    handoff = (git_repo / "COSTANZA.md").read_bytes()
    before = _count(git_repo)
    proc = _git(git_repo, "commit", "-F", str(msg), cwd=nested)
    assert _count(git_repo) == before + 1
    assert (git_repo / "COSTANZA.md").read_bytes() == handoff
    sha = _short_head(git_repo)
    item = load_inbox(git_repo / ".costanza" / "inbox.jsonl").by_id("p1")
    log = git_repo / ".costanza" / "hook.log"
    logged = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert item is not None, proc.stderr + logged
    assert item.status == "proposed"
    assert item.suggested == sha, proc.stderr + logged
    assert item.commit == sha
    assert "sekret" not in logged
    again = invoke(["--root", str(git_repo), "hook", "run", "post-commit"])
    assert again.exit_code == 0, again.output
    assert again.stderr.strip() == ""
    assert _count(git_repo) == before + 1


def test_trailers_and_stamps_follow_config(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    _propose(invoke, git_repo, "leave the hash off")
    msg = git_repo.parent / "cfg-msg.txt"
    msg.write_bytes(b"cfg\n\nCostanza-Accept: p1\n")
    (git_repo / "note.txt").write_text("n\n", encoding="utf-8")
    _git(git_repo, "add", "note.txt")
    _git(git_repo, "commit", "-q", "-F", str(msg))
    config = git_repo / ".costanza" / "config.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("stamp_commits = true", "stamp_commits = false"), encoding="utf-8")
    message = run_post_commit("post-commit", explicit=git_repo)
    assert "suggested for review" in message
    sha = _short_head(git_repo)
    item = load_inbox(git_repo / ".costanza" / "inbox.jsonl").by_id("p1")
    assert item is not None and item.suggested == sha and item.commit is None
    loaded = load_inbox(git_repo / ".costanza" / "inbox.jsonl")
    current = loaded.by_id("p1")
    assert current is not None
    current.suggested = None
    save_inbox(ProjectPaths(git_repo), loaded)
    config.write_text(
        text.replace("apply_trailers = true", "apply_trailers = false"),
        encoding="utf-8",
    )
    stamped = run_post_commit("post-commit", explicit=git_repo)
    assert "suggested" not in stamped
    item = load_inbox(git_repo / ".costanza" / "inbox.jsonl").by_id("p1")
    assert item is not None and item.suggested is None and item.commit == sha


def test_accepted_id_is_named_and_the_hook_exits_zero(
    invoke: InvokeFn, git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(invoke, git_repo)
    _seed(git_repo)
    _propose(invoke, git_repo, "already in the file")
    monkeypatch.setattr("costanza.gate.confirm", lambda *_args, **_kwargs: True)
    accepted = invoke(["--root", str(git_repo), "accept", "p1"])
    assert accepted.exit_code == 0, accepted.output
    msg = git_repo.parent / "accepted-msg.txt"
    msg.write_bytes(b"note\n\nCostanza-Accept: p1\n")
    _git(git_repo, "commit", "-q", "--allow-empty", "-F", str(msg))
    first = run_post_commit("post-commit", explicit=git_repo)
    assert "p1 accepted" in first
    assert "not changed" in first
    logged = (git_repo / ".costanza" / "hook.log").read_text(encoding="utf-8")
    assert "p1 accepted" in logged
    again = invoke(["--root", str(git_repo), "hook", "run", "post-commit"])
    assert again.exit_code == 0, again.output
    assert "p1 accepted" in again.stderr


def test_hook_problems_exit_zero_and_rotate_the_log(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    _propose(invoke, git_repo, "waiting for a commit")
    log = git_repo / ".costanza" / "hook.log"
    log.write_bytes(b"x" * (32 * 1024 + 8))
    result = invoke(["--root", str(git_repo), "hook", "run", "post-commit"])
    assert result.exit_code == 0, result.output
    assert "hook skipped" in result.stderr
    assert "Traceback" not in result.output
    assert (git_repo / ".costanza" / "hook.log.1").is_file()
    body = log.read_text(encoding="utf-8")
    assert "could not read HEAD" in body
    assert len(body.encode("utf-8")) < 32 * 1024
    quiet = invoke(
        ["--root", str(git_repo), "hook", "run", "post-commit"],
        env={"COSTANZA_HOOK": "0"},
    )
    assert quiet.exit_code == 0, quiet.output
    assert quiet.stderr.strip() == ""


def test_review_card_shows_where_files_landed(capsys: pytest.CaptureFixture[str]) -> None:
    configure(no_color=True)
    item = Proposal(id="p4", kind="D", text="landed work", hash="abc", files=["nested/pay.py"])
    item.landing = "abc1234"
    render_review_card(item, 0, 1)
    assert "changed in abc1234" in capsys.readouterr().out
