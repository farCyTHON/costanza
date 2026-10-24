"""Offline tiktoken: a seeded cache counts, anything else estimates once."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from costanza.tokens import (
    FALLBACK_WARNING,
    begin_command,
    bind,
    cache_name,
    measure,
    set_warn,
)


class _Encoder:
    def encode(self, text: str) -> list[int]:
        return [1, 2, 3]


class _Tiktoken:
    @staticmethod
    def get_encoding(name: str) -> _Encoder:
        return _Encoder()


def _seed(cache: Path) -> None:
    cache.mkdir()
    name = cache_name("o200k_base")
    assert name is not None
    (cache / name).write_bytes(b"seed")


def test_seeded_cache_counts_with_tiktoken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache"
    _seed(cache)
    monkeypatch.setattr("costanza.tokens.importlib.import_module", lambda _name: _Tiktoken)
    begin_command()
    bind("tiktoken", "o200k_base", "cache", tmp_path)
    counted, method = measure("hello world")
    assert (counted, method) == (3, "tiktoken")
    assert os.environ.get("TIKTOKEN_CACHE_DIR") != str(cache)


def test_missing_cache_warns_once_and_estimates(tmp_path: Path) -> None:
    begin_command()
    warnings: list[str] = []
    set_warn(warnings.append)
    bind("tiktoken", "o200k_base", str(tmp_path / "missing"), tmp_path)
    first, method = measure("hello world")
    second, _method = measure("hello world")
    assert method == "estimate"
    assert first == second
    assert warnings == [FALLBACK_WARNING]


def test_remote_sockets_are_blocked() -> None:
    import socket

    sock = socket.socket()
    try:
        with pytest.raises(AssertionError, match="network is disabled"):
            sock.connect(("1.1.1.1", 443))
    finally:
        sock.close()


def test_missing_extra_warns_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache"
    _seed(cache)

    def missing(_name: str) -> object:
        raise ImportError("tiktoken is not installed")

    monkeypatch.setattr("costanza.tokens.importlib.import_module", missing)
    begin_command()
    warnings: list[str] = []
    set_warn(warnings.append)
    bind("tiktoken", "o200k_base", str(cache), tmp_path)
    _counted, method = measure("hello")
    measure("again")
    assert method == "estimate"
    assert warnings == [FALLBACK_WARNING]
