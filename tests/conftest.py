from __future__ import annotations

import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from costanza.cli import app
from tests.helpers import InvokeFn, InvokeResult

FIXTURES = Path(__file__).parent / "fixtures"


_REAL_CONNECT = socket.socket.connect
_REAL_CREATE = socket.create_connection
_LOCAL = {"127.0.0.1", "::1", "localhost"}


def _remote(address: object) -> bool:
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    return isinstance(host, str) and host not in _LOCAL


def _block_connect(self: socket.socket, address: object) -> None:
    if _remote(address):
        raise AssertionError(f"network is disabled: {address}")
    _REAL_CONNECT(self, address)  # type: ignore[arg-type]


def _block_create(address: object, *args: object, **kwargs: object) -> socket.socket:
    if _remote(address):
        raise AssertionError(f"network is disabled: {address}")
    return _REAL_CREATE(address, *args, **kwargs)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may open a remote socket. Local IPC, such as asyncio, still works."""
    from costanza.tokens import begin_command

    begin_command()
    monkeypatch.setattr(socket.socket, "connect", _block_connect)
    monkeypatch.setattr(socket, "create_connection", _block_create)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def invoke(runner: CliRunner) -> InvokeFn:
    def _invoke(
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        input: str | None = None,  # noqa: A002
    ) -> InvokeResult:
        merged = {"NO_COLOR": "1", "COLUMNS": "80"}
        if env:
            merged.update(env)
        return runner.invoke(app, args, env=merged, catch_exceptions=False, input=input)

    return _invoke


@pytest.fixture
def tiny_text() -> str:
    return (FIXTURES / "tiny.md").read_text(encoding="utf-8")


@pytest.fixture
def near_text() -> str:
    return (FIXTURES / "near.md").read_text(encoding="utf-8")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "shopbot"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True)
    return repo
