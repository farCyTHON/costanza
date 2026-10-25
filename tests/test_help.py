from __future__ import annotations

from costanza.constants import COMMANDS
from tests.helpers import InvokeFn, strip_ansi


def test_version(invoke: InvokeFn) -> None:
    result = invoke(["--version"])
    assert result.exit_code == 0
    assert strip_ansi(result.stdout).strip() == "costanza 0.1.0"


def test_help_lists_all_commands(invoke: InvokeFn) -> None:
    result = invoke(["--help"])
    assert result.exit_code == 0
    text = strip_ansi(result.stdout)
    for name in COMMANDS:
        assert name in text


def test_every_command_help(invoke: InvokeFn) -> None:
    for name in COMMANDS:
        result = invoke([name, "--help"])
        assert result.exit_code == 0, name
        text = strip_ansi(result.stdout)
        assert "--help" in text
        for flag in ("--root", "--quiet", "--no-color"):
            assert flag in text, f"{name} missing {flag}"
        assert "Global options" in text, name

