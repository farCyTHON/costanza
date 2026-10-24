from __future__ import annotations

from pathlib import Path

import pytest

from costanza.constants import CONFIG_TEXT, IGNORE_LINES, LEDGER_TEXT, skeleton
from tests.helpers import InvokeFn


def test_init_in_git_repo(invoke: InvokeFn, git_repo: Path) -> None:
    result = invoke(["--root", str(git_repo), "init"])
    assert result.exit_code == 0, result.output
    written = (git_repo / "COSTANZA.md").read_bytes()
    assert written == skeleton("shopbot").encode("utf-8")
    assert (git_repo / ".costanza" / "config.toml").read_text(encoding="utf-8") == CONFIG_TEXT
    assert (git_repo / ".costanza" / "archive" / "ids").read_text(encoding="utf-8") == LEDGER_TEXT
    ignore = (git_repo / ".gitignore").read_text(encoding="utf-8")
    for line in IGNORE_LINES:
        assert line in ignore
    assert ignore.count(".costanza/inbox.jsonl") == 1


def test_init_from_subdirectory(
    invoke: InvokeFn, git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = git_repo / "app"
    nested.mkdir()
    monkeypatch.chdir(nested)
    result = invoke(["init"])
    assert result.exit_code == 0
    assert (git_repo / "COSTANZA.md").is_file()
    assert not (nested / "COSTANZA.md").exists()


def test_init_root_outside_git(invoke: InvokeFn, tmp_path: Path) -> None:
    target = tmp_path / "plain"
    target.mkdir()
    result = invoke(["--root", str(target), "init"])
    assert result.exit_code == 0
    assert (target / "COSTANZA.md").is_file()
    assert not (target / ".gitignore").exists()


def test_init_refuses_overwrite(invoke: InvokeFn, git_repo: Path) -> None:
    invoke(["--root", str(git_repo), "init"])
    before = (git_repo / "COSTANZA.md").read_bytes()
    result = invoke(["--root", str(git_repo), "init"])
    assert result.exit_code == 1
    assert "cz init --force" in result.stderr
    assert (git_repo / "COSTANZA.md").read_bytes() == before


def test_init_force_backs_up_and_keeps_ledger(invoke: InvokeFn, git_repo: Path) -> None:
    invoke(["--root", str(git_repo), "init"])
    file_bytes = (git_repo / "COSTANZA.md").read_bytes()
    cfg_bytes = (git_repo / ".costanza" / "config.toml").read_bytes()
    ledger = git_repo / ".costanza" / "archive" / "ids"
    ledger.write_text(LEDGER_TEXT.replace("D 0", "D 9"), encoding="utf-8", newline="\n")
    ledger_before = ledger.read_bytes()
    ignore_before = (git_repo / ".gitignore").read_text(encoding="utf-8")
    result = invoke(["--root", str(git_repo), "init", "--force", "--name", "other"])
    assert result.exit_code == 0
    assert (git_repo / "COSTANZA.md.bak").read_bytes() == file_bytes
    assert (git_repo / ".costanza" / "config.toml.bak").read_bytes() == cfg_bytes
    assert ledger.read_bytes() == ledger_before
    project_line = (git_repo / "COSTANZA.md").read_text(encoding="utf-8").splitlines()[1]
    assert project_line == "# PROJECT: other"
    assert (git_repo / ".gitignore").read_text(encoding="utf-8") == ignore_before


def test_gitignore_covers_transient_costanza_files() -> None:
    from pathlib import Path

    ignore = Path(__file__).resolve().parents[1].joinpath(".gitignore").read_text(encoding="utf-8")
    for line in (
        ".costanza/inbox.jsonl",
        ".costanza/backup/",
        ".costanza/hook.log",
    ):
        assert line in ignore
        assert line in IGNORE_LINES
    assert ".costanza/archive/" not in ignore.splitlines()
    assert ".costanza/archive/" not in IGNORE_LINES
    assert ".costanza/archive/ids" not in ignore.splitlines()


def test_init_name(invoke: InvokeFn, tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    result = invoke(["--root", str(target), "init", "--name", "shopbot, order bot"])
    assert result.exit_code == 0
    assert "# PROJECT: shopbot, order bot" in (target / "COSTANZA.md").read_text(encoding="utf-8")


def test_quiet_init(invoke: InvokeFn, tmp_path: Path) -> None:
    target = tmp_path / "q"
    target.mkdir()
    result = invoke(["--quiet", "--root", str(target), "init"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert "initialized" not in result.stderr
