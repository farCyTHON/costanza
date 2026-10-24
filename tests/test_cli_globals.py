from __future__ import annotations

from pathlib import Path

from tests.helpers import InvokeFn, InvokeResult


def test_no_color_flag_and_env(invoke: InvokeFn, tmp_path: Path) -> None:
    result: InvokeResult = invoke(["--root", str(tmp_path), "init"])
    assert "\x1b" not in result.stdout + result.stderr
    result2: InvokeResult = invoke(
        ["--root", str(tmp_path), "init"],
        env={"NO_COLOR": "1"},
    )
    assert result2.exit_code == 1
    assert "\x1b" not in result2.stdout + result2.stderr


def test_globals_before_and_after(invoke: InvokeFn, tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    a = invoke(["--no-color", "--root", str(first), "init"])
    b = invoke(["init", "--no-color", "--root", str(second)])
    assert a.exit_code == 0 and b.exit_code == 0
    assert a.stdout.replace(str(first), "ROOT") == b.stdout.replace(str(second), "ROOT")

    c = invoke(["--quiet", "--root", str(first), "status"])
    d = invoke(["status", "--quiet", "--root", str(first)])
    assert c.stdout == d.stdout
    assert c.exit_code == d.exit_code == 0


def test_later_root_wins(invoke: InvokeFn, tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    invoke(["--root", str(a), "init"])
    result: InvokeResult = invoke(["--root", str(a), "status", "--root", str(b)])
    assert result.exit_code == 1
    assert "cz init" in result.stderr


def test_version_only_before_command(invoke: InvokeFn) -> None:
    result: InvokeResult = invoke(["status", "--version"])
    assert result.exit_code == 2


def test_state_does_not_leak(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--quiet", "--root", str(tmp_path), "init"])
    result: InvokeResult = invoke(["--root", str(tmp_path), "status"])
    assert "NOW" in result.stdout


def test_ascii_bytes(invoke: InvokeFn, tmp_path: Path) -> None:
    result: InvokeResult = invoke(
        ["--root", str(tmp_path), "init"],
        env={"COSTANZA_ASCII": "1"},
    )
    assert result.exit_code == 0
    blob = (result.stdout + result.stderr).encode("utf-8")
    assert all(byte < 0x80 for byte in blob)
    result2: InvokeResult = invoke(
        ["--root", str(tmp_path), "init"],
        env={"COSTANZA_ASCII": "1"},
    )
    assert result2.exit_code == 1
    blob2 = (result2.stdout + result2.stderr).encode("utf-8")
    assert all(byte < 0x80 for byte in blob2)
