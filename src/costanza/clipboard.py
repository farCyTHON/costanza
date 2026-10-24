"""Copy and read the system clipboard. No network, no extra dependencies.

Windows uses the Win32 Unicode clipboard (never clip.exe). Other platforms
use the first available tool: pbcopy, wl-copy, xclip, then xsel.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Final

from costanza.constants import CLIPBOARD_HINT, CLIPBOARD_TIMEOUT
from costanza.exceptions import ClipboardError, ClipboardUnavailable

CF_UNICODETEXT: Final = 13
GMEM_MOVEABLE: Final = 0x0002
OPEN_RETRY_S: Final = 1.0
OPEN_SLEEP_S: Final = 0.05


@dataclass(frozen=True)
class CopyResult:
    backend: str
    verified: bool


@dataclass(frozen=True)
class _UnixBackend:
    name: str
    write_argv: tuple[str, ...]
    read_argv: tuple[str, ...] | None
    env: dict[str, str] | None = None


def platform_name() -> str:
    """Return ``sys.platform``. Isolated so tests can fake the OS."""
    return sys.platform


def _is_windows() -> bool:
    return platform_name() == "win32"


def _which(name: str) -> str | None:
    return shutil.which(name)


def _first_diff(expected: str, actual: str) -> int:
    limit = min(len(expected), len(actual))
    for index in range(limit):
        if expected[index] != actual[index]:
            return index
    return limit


def _mismatch(expected: str, actual: str) -> ClipboardError:
    at = _first_diff(expected, actual)
    return ClipboardError(
        f"the clipboard changed the text (first difference at character {at}); printed to stdout instead",
        CLIPBOARD_HINT,
    )


def _run_tool(
    argv: tuple[str, ...],
    data: bytes | None,
    env: dict[str, str] | None,
) -> subprocess.CompletedProcess[bytes]:
    exe = _which(argv[0])
    if exe is None:
        raise FileNotFoundError(argv[0])
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        return subprocess.run(
            [exe, *argv[1:]],
            input=data,
            capture_output=True,
            timeout=CLIPBOARD_TIMEOUT,
            check=False,
            env=merged,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClipboardError(
            f"{argv[0]} timed out after {CLIPBOARD_TIMEOUT} seconds; printed to stdout instead",
            CLIPBOARD_HINT,
        ) from exc


def _unix_backends() -> list[_UnixBackend]:
    plat = platform_name()
    extra_lang = {"LANG": "en_US.UTF-8"}
    if plat == "darwin":
        return [
            _UnixBackend("pbcopy", ("pbcopy",), ("pbpaste",), extra_lang),
        ]
    backends: list[_UnixBackend] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        backends.append(
            _UnixBackend("wl-copy", ("wl-copy",), ("wl-paste", "--no-newline")),
        )
    backends.append(
        _UnixBackend(
            "xclip",
            ("xclip", "-selection", "clipboard"),
            ("xclip", "-selection", "clipboard", "-o"),
        )
    )
    backends.append(
        _UnixBackend(
            "xsel",
            ("xsel", "--clipboard", "--input"),
            ("xsel", "--clipboard", "--output"),
        )
    )
    return backends


def _copy_unix(text: str) -> CopyResult:
    payload = text.encode("utf-8")
    last_error: Exception | None = None
    for backend in _unix_backends():
        if _which(backend.write_argv[0]) is None:
            continue
        try:
            written = _run_tool(backend.write_argv, payload, backend.env)
        except ClipboardError:
            raise
        except FileNotFoundError as exc:
            last_error = exc
            continue
        if written.returncode != 0:
            last_error = ClipboardError(
                f"{backend.name} failed to copy; printed to stdout instead",
                CLIPBOARD_HINT,
            )
            continue
        if backend.read_argv is None or _which(backend.read_argv[0]) is None:
            return CopyResult(backend=backend.name, verified=False)
        try:
            read = _run_tool(backend.read_argv, None, backend.env)
        except ClipboardError:
            raise
        except FileNotFoundError:
            return CopyResult(backend=backend.name, verified=False)
        if read.returncode != 0:
            return CopyResult(backend=backend.name, verified=False)
        actual = read.stdout.decode("utf-8")
        if actual != text:
            raise _mismatch(text, actual)
        return CopyResult(backend=backend.name, verified=True)
    if last_error is not None and isinstance(last_error, ClipboardError):
        raise last_error
    raise ClipboardUnavailable("no clipboard tool found; printed to stdout instead", CLIPBOARD_HINT)


if sys.platform == "win32":

    def _win32_dlls() -> tuple[Any, Any]:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        return kernel32, user32

    def _open_clipboard(user32: Any) -> None:
        deadline = time.monotonic() + OPEN_RETRY_S
        while time.monotonic() < deadline:
            if user32.OpenClipboard(None):
                return
            time.sleep(OPEN_SLEEP_S)
        raise ClipboardError("the Windows clipboard is busy; printed to stdout instead", CLIPBOARD_HINT)

    def _read_win32_unlocked(kernel32: Any, user32: Any) -> str:
        import ctypes

        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            raise ClipboardError("the Windows clipboard was empty after copy", CLIPBOARD_HINT)
        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise ClipboardError("the Windows clipboard could not be read back", CLIPBOARD_HINT)
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)

    def _copy_win32(text: str) -> CopyResult:
        import ctypes

        kernel32, user32 = _win32_dlls()
        payload = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not handle:
            raise ClipboardError("the Windows clipboard could not allocate memory", CLIPBOARD_HINT)
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise ClipboardError("the Windows clipboard could not lock memory", CLIPBOARD_HINT)
        ctypes.memmove(locked, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        owned = True
        try:
            _open_clipboard(user32)
            try:
                if not user32.EmptyClipboard():
                    raise ClipboardError("the Windows clipboard could not be emptied", CLIPBOARD_HINT)
                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    raise ClipboardError("the Windows clipboard rejected the text", CLIPBOARD_HINT)
                owned = False
            finally:
                user32.CloseClipboard()
            _open_clipboard(user32)
            try:
                actual = _read_win32_unlocked(kernel32, user32)
            finally:
                user32.CloseClipboard()
            if actual != text:
                raise _mismatch(text, actual)
            return CopyResult(backend="win32", verified=True)
        finally:
            if owned:
                kernel32.GlobalFree(handle)

    def _read_win32() -> str:
        kernel32, user32 = _win32_dlls()
        _open_clipboard(user32)
        try:
            return _read_win32_unlocked(kernel32, user32)
        finally:
            user32.CloseClipboard()

else:

    def _copy_win32(text: str) -> CopyResult:
        raise ClipboardUnavailable("no clipboard tool found; printed to stdout instead", CLIPBOARD_HINT)

    def _read_win32() -> str:
        raise ClipboardUnavailable(
            "no clipboard tool found",
            "cz paste --file reply.txt, or pipe the reply to cz paste",
        )


def _read_unix() -> str:
    last_error: Exception | None = None
    for backend in _unix_backends():
        if backend.read_argv is None or _which(backend.read_argv[0]) is None:
            continue
        try:
            read = _run_tool(backend.read_argv, None, backend.env)
        except ClipboardError:
            raise
        except FileNotFoundError as exc:
            last_error = exc
            continue
        if read.returncode != 0:
            last_error = ClipboardError(
                f"{backend.name} failed to read the clipboard",
                "cz paste --file reply.txt",
            )
            continue
        return read.stdout.decode("utf-8")
    if last_error is not None and isinstance(last_error, ClipboardError):
        raise last_error
    raise ClipboardUnavailable(
        "no clipboard tool found",
        "cz paste --file reply.txt, or pipe the reply to cz paste",
    )


def copy(text: str) -> CopyResult:
    """Put ``text`` on the clipboard and read it back when a reader exists."""
    if _is_windows():
        return _copy_win32(text)
    return _copy_unix(text)


def read() -> str:
    """Return clipboard text, or raise if no backend can read it."""
    if _is_windows():
        return _read_win32()
    return _read_unix()
