from __future__ import annotations

import io
import re
import sys

import pytest
from typer.testing import CliRunner

from costanza import ui
from costanza.cli import app
from costanza.ui import _WELCOME_COMMANDS, HELP_LINE, TAGLINE
from tests.helpers import InvokeFn

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_FIVE = ("init", "decide", "review", "handoff", "paste")


class _Tty(io.StringIO):
    def __init__(self, encoding: str) -> None:
        super().__init__()
        self._encoding = encoding

    def isatty(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return self._encoding


def _visible(text: str) -> list[str]:
    return [_ANSI.sub("", line) for line in text.splitlines()]


def test_welcome_exits_0_and_plain_lists_commands(invoke: InvokeFn) -> None:
    result = invoke(["welcome"])
    assert result.exit_code == 0
    assert TAGLINE in result.stdout
    assert HELP_LINE in result.stdout
    for name in _FIVE:
        assert name in result.stdout
    assert "\x1b" not in result.stdout + result.stderr
    assert "\u2588" not in result.stdout


def test_no_args_matches_welcome(invoke: InvokeFn) -> None:
    bare = invoke([])
    named = invoke(["welcome"])
    assert bare.exit_code == 0
    assert named.exit_code == 0
    assert bare.stdout == named.stdout
    assert bare.stderr == named.stderr
    assert TAGLINE in bare.stdout
    assert "Usage:" not in bare.stdout


def test_quiet_and_no_color_stay_plain(invoke: InvokeFn) -> None:
    for args in (["--quiet", "welcome"], ["-q", "welcome"], ["--no-color", "welcome"]):
        result = invoke(args)
        assert result.exit_code == 0, args
        assert TAGLINE in result.stdout
        for name in _FIVE:
            assert name in result.stdout
        assert "\u2588" not in result.stdout
        assert "\x1b" not in result.stdout + result.stderr


def test_pipe_has_no_ansi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    result = CliRunner().invoke(app, ["welcome"], env={"COLUMNS": "80", "NO_COLOR": ""})
    assert result.exit_code == 0
    assert TAGLINE in result.output
    assert "\x1b" not in result.output
    for name in _FIVE:
        assert name in result.output


def test_descriptions_are_six_words() -> None:
    assert len(_WELCOME_COMMANDS) == 5
    for _name, desc in _WELCOME_COMMANDS:
        assert len(desc.split()) == 6


def test_block_banner_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _Tty("utf-8")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("COSTANZA_ASCII", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    ui.configure(no_color=False, quiet=False, color_policy="always", ascii_policy="never")
    ui.render_welcome("0.1.0")
    text = stream.getvalue()
    lines = _visible(text)
    assert "\u2588" in text
    assert TAGLINE in text
    assert len(lines) < 20
    assert all(len(line) < 80 for line in lines)


def test_ascii_fallback_when_blocks_will_not_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _Tty("cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("COSTANZA_ASCII", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    ui.configure(no_color=False, quiet=False, color_policy="always")
    ui.render_welcome("0.1.0")
    text = stream.getvalue()
    assert "\u2588" not in text
    assert "######" in text
    assert TAGLINE in text
    text.encode("cp1252")


def test_background_panel_only_in_colour_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    colour = _Tty("utf-8")
    monkeypatch.setattr(sys, "stdout", colour)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("COSTANZA_ASCII", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    ui.configure(no_color=False, quiet=False, color_policy="always", ascii_policy="never")
    ui.render_welcome("0.1.0")
    painted = colour.getvalue()
    assert "48;2;20;16;15" in painted
    assert painted.count("48;2;20;16;15") >= 7
    assert "╭" in painted and "╮" in painted and "╰" in painted and "╯" in painted
    assert "\x1b[?1049" not in painted
    assert "\x1b[2J" not in painted
    assert all(len(line) <= 80 for line in _visible(painted))

    ascii_stream = _Tty("cp1252")
    monkeypatch.setattr(sys, "stdout", ascii_stream)
    ui.configure(no_color=False, quiet=False, color_policy="always")
    ui.render_welcome("0.1.0")
    hashed = ascii_stream.getvalue()
    assert "######" in hashed
    assert "48;2;20;16;15" not in hashed
    assert "╭" not in hashed

    plain = _Tty("utf-8")
    monkeypatch.setattr(sys, "stdout", plain)
    ui.configure(no_color=True, quiet=False, color_policy="always", ascii_policy="never")
    ui.render_welcome("0.1.0")
    bare = plain.getvalue()
    assert TAGLINE in bare
    assert "48;2;20;16;15" not in bare
    assert "╭" not in bare
    assert "\x1b" not in bare


def test_narrow_terminal_is_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _Tty("utf-8")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLUMNS", "59")
    ui.configure(no_color=False, quiet=False, color_policy="always", ascii_policy="never")
    ui.render_welcome("0.1.0")
    text = stream.getvalue()
    assert "\u2588" not in text
    assert "######" not in text
    assert TAGLINE in text
    assert "\x1b" not in text
