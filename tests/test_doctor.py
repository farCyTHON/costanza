"""doctor: reports, read-only by default, and the four --fix repairs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from costanza.doctor import CHECK_NAMES, run_doctor
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init"])
    assert result.exit_code == 0, result.stdout + result.stderr


def _put(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _stale_lock(root: Path) -> Path:
    path = root / ".costanza" / "lock"
    _put(path, "pid=1\nts=2020-01-01T00:00:00Z\n")
    return path


def _drop_ignore_line(root: Path) -> Path:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8")
    updated = text.replace(".costanza/inbox.jsonl\n", "")
    assert updated != text
    _put(path, updated)
    return path


def _add_decisions(root: Path, body: str) -> None:
    path = root / "COSTANZA.md"
    text = path.read_text(encoding="utf-8")
    needle = "## DECISIONS\n\n"
    assert needle in text
    _put(path, text.replace(needle, "## DECISIONS\n" + body + "\n", 1))


def test_doctor_reports_every_check(invoke: InvokeFn, tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    _init(invoke, root)
    result = invoke(["--root", str(root), "doctor", "--json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert [item["name"] for item in payload["checks"]] == list(CHECK_NAMES)
    assert {item["status"] for item in payload["checks"]} <= {"ok", "warn", "fail"}
    assert all(item["status"] != "fail" for item in payload["checks"])


def test_doctor_without_fix_writes_nothing(invoke: InvokeFn, git_repo: Path) -> None:
    _init(invoke, git_repo)
    lock = _stale_lock(git_repo)
    ignore = _drop_ignore_line(git_repo)
    handoff = git_repo / "COSTANZA.md"
    ledger = git_repo / ".costanza" / "archive" / "ids"
    agents = git_repo / "AGENTS.md"
    before = {
        "lock": lock.read_bytes(),
        "ignore": ignore.read_bytes(),
        "handoff": handoff.read_bytes(),
        "ledger": ledger.read_bytes(),
        "agents": agents.read_bytes() if agents.is_file() else b"",
    }
    result = invoke(["--root", str(git_repo), "doctor"])
    blob = result.stdout + result.stderr
    assert result.exit_code == 3, blob
    assert lock.read_bytes() == before["lock"]
    assert ignore.read_bytes() == before["ignore"]
    assert ".costanza/inbox.jsonl" not in ignore.read_text(encoding="utf-8")
    assert handoff.read_bytes() == before["handoff"]
    assert ledger.read_bytes() == before["ledger"]
    assert (agents.read_bytes() if agents.is_file() else b"") == before["agents"]
    assert "stale lock" in blob
    assert ".costanza/inbox.jsonl" in blob


def test_fix_repairs_lock_gitignore_and_ledger_without_a_tty(
    invoke: InvokeFn, git_repo: Path
) -> None:
    _init(invoke, git_repo)
    lock = _stale_lock(git_repo)
    ignore = _drop_ignore_line(git_repo)
    _add_decisions(git_repo, "D1 keep one file -- simple")
    ledger = git_repo / ".costanza" / "archive" / "ids"
    assert "D 0" in ledger.read_text(encoding="utf-8")
    result = invoke(["--root", str(git_repo), "doctor", "--fix"])
    blob = result.stdout + result.stderr
    assert result.exit_code == 0, blob
    assert not lock.exists()
    assert ".costanza/inbox.jsonl" in ignore.read_text(encoding="utf-8")
    assert "D 1" in ledger.read_text(encoding="utf-8")
    assert "duplicate IDs need" not in blob


def test_live_lock_is_a_warning_and_stays(invoke: InvokeFn, tmp_path: Path) -> None:
    root = tmp_path / "live"
    root.mkdir()
    _init(invoke, root)
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lock = root / ".costanza" / "lock"
    _put(lock, f"pid=1\nts={stamp}\n")
    preview = invoke(["--root", str(root), "doctor"])
    assert preview.exit_code == 0, preview.stdout + preview.stderr
    assert "left in place" in (preview.stdout + preview.stderr)
    assert lock.is_file()
    fixed = invoke(["--root", str(root), "doctor", "--fix"])
    assert fixed.exit_code == 0, fixed.stdout + fixed.stderr
    assert lock.read_text(encoding="utf-8").startswith("pid=1\n")


def test_duplicate_ids_need_a_confirmed_gate(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "dups"
    root.mkdir()
    _init(invoke, root)
    _add_decisions(root, "D1 keep one file -- simple\nD1 see D1 again -- duplicate")
    skipped = invoke(["--root", str(root), "doctor", "--fix"])
    blob = skipped.stdout + skipped.stderr
    assert skipped.exit_code == 3, blob
    assert "duplicate IDs need cz doctor --fix in your own terminal" in blob
    text = (root / "COSTANZA.md").read_text(encoding="utf-8")
    assert text.count("\nD1 ") == 2

    monkeypatch.setattr("costanza.gate.confirm", lambda *args, **kwargs: True)
    renamed = invoke(["--root", str(root), "doctor", "--fix"])
    assert renamed.exit_code == 0, renamed.stdout + renamed.stderr
    assert "references to D1 in text were not changed" in renamed.stdout
    updated = (root / "COSTANZA.md").read_text(encoding="utf-8")
    assert "\nD1 keep one file -- simple\n" in updated
    assert "see D1 again" in updated
    assert "\nD2 " in updated
    assert updated.count("\nD1 ") == 1


def test_warnings_do_not_fail_and_bad_config_does(invoke: InvokeFn, tmp_path: Path) -> None:
    root = tmp_path / "cfg"
    root.mkdir()
    _init(invoke, root)
    config = root / ".costanza" / "config.toml"
    original = config.read_text(encoding="utf-8")
    _put(config, original + "\nstray = true\n")
    warned = invoke(["--root", str(root), "doctor"])
    assert warned.exit_code == 0, warned.stdout + warned.stderr
    assert "stray" in (warned.stdout + warned.stderr)

    _put(config, 'version = 1\n[budget]\ntokens = "nope"\n')
    failed = invoke(["--root", str(root), "doctor"])
    blob = failed.stdout + failed.stderr
    assert failed.exit_code == 3, blob
    assert "tokens" in blob
    assert "python" in blob
    assert "extras" in blob


def test_python_version_bounds(invoke: InvokeFn, tmp_path: Path) -> None:
    root = tmp_path / "py"
    root.mkdir()
    _init(invoke, root)
    for version in ((3, 10), (3, 13)):
        report = run_doctor(explicit=root, version=version)
        assert report.checks[0].name == "python"
        assert report.checks[0].status == "ok"
    for version in ((3, 9), (3, 14)):
        report = run_doctor(explicit=root, version=version)
        assert report.checks[0].status == "fail"
        assert report.failed
