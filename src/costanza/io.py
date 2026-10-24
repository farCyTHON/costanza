"""UTF-8 file helpers. Core: no Rich, no Typer."""

from __future__ import annotations

import os
from pathlib import Path


def read_text(path: Path) -> str:
    """Read UTF-8, dropping a leading BOM. Newlines stay as in the file."""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8")


def write_text(path: Path, text: str) -> None:
    """Write UTF-8, LF, no BOM, with a final newline, replacing atomically."""
    if not text.endswith("\n"):
        text += "\n"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def write_bytes(path: Path, data: bytes) -> None:
    """Write exact bytes atomically. Callers own encoding, BOM and newlines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def copy_bytes(src: Path, dest: Path) -> None:
    """Copy exact bytes, replacing ``dest`` atomically."""
    write_bytes(dest, src.read_bytes())
