from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from costanza.clipboard import copy, read
from costanza.constants import CLIPBOARD_HINT
from costanza.exceptions import ClipboardError, ClipboardUnavailable

APPENDIX_A = (
    "Café naïve façade — Ελληνικά Русский 中文 日本語 한국어 עברית العربية\n"
    "emoji 🎉 👩‍💻 🇺🇦 ✓ █ →\n"
    "\tindented line\n"
    "last line"
)


def test_unix_backends_never_include_clip_exe() -> None:
    from costanza.clipboard import _unix_backends

    for backend in _unix_backends():
        assert "clip.exe" not in backend.name
        assert all("clip.exe" not in part.lower() for part in backend.write_argv)


def test_copy_never_runs_clip_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "linux")
    monkeypatch.setattr("costanza.clipboard._which", lambda name: None if "clip" in name else None)
    monkeypatch.setattr("costanza.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardUnavailable) as caught:
        copy("hello")
    assert "no clipboard tool found" in caught.value.message
    assert CLIPBOARD_HINT in caught.value.hint
    assert caught.value.__traceback__ is not None
    for argv in calls:
        joined = " ".join(argv).lower()
        assert "clip.exe" not in joined
        assert not any(part.lower() == "clip.exe" or part.lower().endswith("\\clip.exe") for part in argv)


def test_unix_backends_tried_in_spec_order(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_which(name: str) -> str | None:
        mapping = {
            "pbcopy": "/bin/pbcopy",
            "pbpaste": "/bin/pbpaste",
            "wl-copy": "/bin/wl-copy",
            "wl-paste": "/bin/wl-paste",
            "xclip": "/bin/xclip",
            "xsel": "/bin/xsel",
        }
        return mapping.get(name)

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(argv[0] if argv else "")
        payload = kwargs.get("input")
        if payload is None:
            return subprocess.CompletedProcess(argv, 0, stdout=b"hello", stderr=b"")
        assert payload == b"hello"
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "darwin")
    monkeypatch.setattr("costanza.clipboard._which", fake_which)
    monkeypatch.setattr("costanza.clipboard.subprocess.run", fake_run)
    result = copy("hello")
    assert result.backend == "pbcopy"
    assert result.verified
    assert "/bin/pbcopy" in seen[0] or seen[0].endswith("pbcopy")

    seen.clear()
    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    result = copy("hello")
    assert result.backend == "wl-copy"

    seen.clear()
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def which_x(name: str) -> str | None:
        if name in {"xclip", "xsel"}:
            return f"/bin/{name}"
        return None

    monkeypatch.setattr("costanza.clipboard._which", which_x)
    result = copy("hello")
    assert result.backend == "xclip"


def test_hanging_tool_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str | None:
        return f"/bin/{name}" if name in {"pbcopy", "pbpaste"} else None

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="pbcopy", timeout=5)

    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "darwin")
    monkeypatch.setattr("costanza.clipboard._which", fake_which)
    monkeypatch.setattr("costanza.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as caught:
        copy("hello")
    assert "timed out" in caught.value.message


def test_readback_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str | None:
        return f"/bin/{name}" if name in {"pbcopy", "pbpaste"} else None

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if kwargs.get("input") is not None:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(argv, 0, stdout=b"other", stderr=b"")

    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "darwin")
    monkeypatch.setattr("costanza.clipboard._which", fake_which)
    monkeypatch.setattr("costanza.clipboard.subprocess.run", fake_run)
    with pytest.raises(ClipboardError) as caught:
        copy("hello")
    assert "first difference at character" in caught.value.message


def test_unverified_when_no_readback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(name: str) -> str | None:
        return "/bin/pbcopy" if name == "pbcopy" else None

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "darwin")
    monkeypatch.setattr("costanza.clipboard._which", fake_which)
    monkeypatch.setattr("costanza.clipboard.subprocess.run", fake_run)
    result = copy("hello")
    assert result.backend == "pbcopy"
    assert result.verified is False


def test_pbcopy_gets_lang_and_utf8_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    def fake_which(name: str) -> str | None:
        return f"/bin/{name}" if name in {"pbcopy", "pbpaste"} else None

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        recorded["argv"] = argv
        if kwargs.get("input") is not None:
            recorded["input"] = kwargs.get("input")
            recorded["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(argv, 0, stdout="Café".encode(), stderr=b"")

    monkeypatch.setattr("costanza.clipboard.platform_name", lambda: "darwin")
    monkeypatch.setattr("costanza.clipboard._which", fake_which)
    monkeypatch.setattr("costanza.clipboard.subprocess.run", fake_run)
    result = copy("Café")
    assert result.verified
    assert recorded["input"] == "Café".encode()
    assert recorded["env"]["LANG"] == "en_US.UTF-8"


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 clipboard round-trip")
def test_win32_roundtrip_appendix_a() -> None:
    original: str | None = None
    try:
        original = read()
    except (ClipboardUnavailable, ClipboardError):
        original = None
    result = copy(APPENDIX_A)
    assert result.backend == "win32"
    assert result.verified
    assert read() == APPENDIX_A
    if original is not None:
        copy(original)


def test_unavailable_is_costanza_error() -> None:
    err = ClipboardUnavailable("no clipboard tool found", CLIPBOARD_HINT)
    assert err.exit_code == 1
    assert "no clipboard" in err.message
