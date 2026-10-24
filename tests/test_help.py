from __future__ import annotations

from costanza.constants import COMMANDS
from tests.helpers import InvokeFn


def test_version(invoke: InvokeFn) -> None:
    result = invoke(["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "costanza 0.1.0"


def test_help_lists_all_commands(invoke: InvokeFn) -> None:
    result = invoke(["--help"])
    assert result.exit_code == 0
    for name in COMMANDS:
        assert name in result.stdout


def test_every_command_help(invoke: InvokeFn) -> None:
    for name in COMMANDS:
        result = invoke([name, "--help"])
        assert result.exit_code == 0, name
        assert "--help" in result.stdout
        for flag in ("--root", "--quiet", "--no-color"):
            assert flag in result.stdout, f"{name} missing {flag}"
        assert "Global options" in result.stdout, name

