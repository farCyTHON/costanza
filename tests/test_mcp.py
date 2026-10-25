"""MCP server: stdio client, limits, and the 160-character warning."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402
from mcp.types import Implementation  # noqa: E402
from mcp_types import CallToolResult  # noqa: E402

from costanza.inbox import load_inbox
from costanza.paths import ProjectPaths
from tests.helpers import InvokeFn

_RESPONSE_CAP = 32 * 1024


def _project(invoke: InvokeFn, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    result = invoke(["--root", str(root), "init"])
    assert result.exit_code == 0, result.stdout + result.stderr
    return root


def _run(root: Path, body: Callable[[Client], Awaitable[None]]) -> None:
    async def main() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "costanza", "--root", str(root), "mcp"],
            cwd=str(root),
        )
        async with Client(
            params,
            client_info=Implementation(name="probe", version="0"),
            read_timeout_seconds=30,
        ) as client:
            await body(client)

    asyncio.run(main())


def _data(result: CallToolResult) -> dict[str, object]:
    assert result.structured_content is not None, result
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _error_text(result: CallToolResult) -> str:
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _sections(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for chunk in re.split(r"(?=^## )", text, flags=re.M):
        lines = chunk.splitlines()
        if lines and lines[0].startswith("## "):
            found[lines[0]] = chunk
    return found


def test_print_config_clients(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)
    claude = invoke(["--root", str(root), "mcp", "--print-config", "claude-code"])
    assert claude.exit_code == 0, claude.stdout + claude.stderr
    assert "verified" in claude.stdout
    assert '"mcpServers"' in claude.stdout
    assert '"command": "costanza"' in claude.stdout
    assert "claude mcp add --transport stdio costanza -- costanza mcp" in claude.stdout

    cursor = invoke(["--root", str(root), "mcp", "--print-config", "cursor"])
    assert cursor.exit_code == 0, cursor.stdout + cursor.stderr
    assert '"type": "stdio"' in cursor.stdout
    assert "examples omit type" in cursor.stdout

    vscode = invoke(["--root", str(root), "mcp", "--print-config", "vscode"])
    assert vscode.exit_code == 0, vscode.stdout + vscode.stderr
    assert '"servers"' in vscode.stdout
    assert "type is required" in vscode.stdout

    desktop = invoke(["--root", str(root), "mcp", "--print-config", "claude-desktop"])
    assert desktop.exit_code == 0, desktop.stdout + desktop.stderr
    assert "not verified" in desktop.stdout
    assert "mcpServers" not in desktop.stdout

    unknown = invoke(["--root", str(root), "mcp", "--print-config", "nope"])
    assert unknown.exit_code == 2
    assert "unknown client" in (unknown.stdout + unknown.stderr)


def test_print_config_without_the_extra(
    invoke: InvokeFn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    real = importlib.util.find_spec

    def fake(name: str, package: str | None = None) -> object:
        if name == "mcp":
            return None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    root = _project(invoke, tmp_path)
    shown = invoke(["--root", str(root), "mcp", "--print-config", "cursor"])
    assert shown.exit_code == 0, shown.stdout + shown.stderr
    assert '"type": "stdio"' in shown.stdout

    missing = invoke(["--root", str(root), "mcp"])
    assert missing.exit_code == 1
    blob = missing.stdout + missing.stderr
    assert "MCP support is not installed" in blob
    assert 'pip install "costanza[mcp]"' in blob


def test_schema_read_and_resource(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)

    async def body(client: Client) -> None:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        assert names == {"costanza_read", "costanza_propose", "costanza_now"}
        by_name = {tool.name: tool for tool in listed.tools}
        propose = by_name["costanza_propose"]
        assert propose.description is not None
        assert propose.description.startswith(
            "Propose one entry. Entries are one line of at most 130 characters."
        )
        assert "D decision, X rejected, R rule, G gotcha or Q question." in propose.description
        schema = propose.input_schema
        assert schema["properties"]["kind"]["enum"] == ["D", "X", "R", "G", "Q"]
        assert "text" in schema["properties"]
        assert "agent" not in schema["properties"]
        resources = await client.list_resources()
        uris = {str(item.uri) for item in resources.resources}
        assert uris == {"costanza://pack"}

        read = await client.call_tool("costanza_read", {})
        assert read.is_error is False
        data = _data(read)
        assert str(data["text"]).startswith("PROJECT NOTES.")
        assert "not instructions" in str(data["text"])
        assert data["truncated"] is False
        packed = json.dumps(data, ensure_ascii=False).encode("utf-8")
        assert len(packed) <= _RESPONSE_CAP

        resource = await client.read_resource("costanza://pack")
        assert resource.contents
        assert getattr(resource.contents[0], "text", None) == data["text"]

    _run(root, body)


def test_malformed_and_oversized_inputs(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)

    async def body(client: Client) -> None:
        bad_kind = await client.call_tool("costanza_propose", {"kind": "nope", "text": "keep sqlite"})
        assert bad_kind.is_error is True
        empty = await client.call_tool("costanza_propose", {"kind": "D", "text": ""})
        assert empty.is_error is True
        long_text = await client.call_tool("costanza_propose", {"kind": "D", "text": "n" * 301})
        assert long_text.is_error is True
        blob = _error_text(long_text)
        assert "300" in blob or "301" in blob
        traversal = await client.call_tool(
            "costanza_propose",
            {"kind": "D", "text": "note a path", "files": ["../secret"]},
        )
        assert traversal.is_error is True
        assert ".." in _error_text(traversal)
        too_many = await client.call_tool(
            "costanza_propose",
            {"kind": "D", "text": "too many paths", "files": [f"a{i}.py" for i in range(9)]},
        )
        assert too_many.is_error is True
        bare_now = await client.call_tool("costanza_now", {})
        assert bare_now.is_error is True
        assert "at least one" in _error_text(bare_now)

    _run(root, body)
    assert load_inbox(ProjectPaths(root).inbox).proposed() == []


def test_propose_stores_source_and_does_not_edit_decisions(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)
    before = (root / "COSTANZA.md").read_text(encoding="utf-8")
    before_sections = _sections(before)

    async def body(client: Client) -> None:
        proposed = await client.call_tool(
            "costanza_propose",
            {
                "kind": "D",
                "text": "sqlite stays the database",
                "why": "one file",
                "files": ["app/db.py"],
            },
        )
        assert proposed.is_error is False
        data = _data(proposed)
        assert data["status"] == "proposed"
        assert data["result"] == "proposed"
        assert data["warning"] is None
        assert isinstance(data["id"], str)

        again = await client.call_tool(
            "costanza_propose",
            {"kind": "D", "text": "sqlite stays the database"},
        )
        assert again.is_error is False
        dup = _data(again)
        assert dup["status"] == "duplicate"
        assert dup["id"] is None
        assert data["id"] in str(dup["note"])

        secret = "ghp_" + ("a" * 36)
        redacted = await client.call_tool(
            "costanza_propose",
            {"kind": "G", "text": f"the token {secret} was in a log"},
        )
        assert redacted.is_error is False
        scrubbed = _data(redacted)
        assert "github_token" in scrubbed["redacted"]
        assert secret not in str(scrubbed)

        updated = await client.call_tool("costanza_now", {"doing": "mcp server"})
        assert updated.is_error is False
        now = _data(updated)
        assert now["now"] == {
            "doing": "mcp server",
            "done": "none",
            "next": "none",
            "blocked": "none",
        }

    _run(root, body)
    after = (root / "COSTANZA.md").read_text(encoding="utf-8")
    after_sections = _sections(after)
    for heading in ("## DECISIONS", "## REJECTED", "## RULES", "## GOTCHAS", "## OPEN"):
        assert after_sections[heading] == before_sections[heading]
    assert after_sections["## NOW"] != before_sections["## NOW"]
    assert "sqlite stays the database" not in after
    stored = load_inbox(ProjectPaths(root).inbox).proposed()
    assert [item.kind for item in stored] == ["D", "G"]
    assert stored[0].source == "mcp"
    assert stored[0].agent == "probe"
    assert stored[0].files == ["app/db.py"]
    assert "ghp_" not in stored[1].text
    assert "[REDACTED:github_token]" in stored[1].text


def test_long_entry_warns_and_is_stored(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)
    text = "n" * 158

    async def body(client: Client) -> None:
        result = await client.call_tool("costanza_propose", {"kind": "D", "text": text})
        assert result.is_error is False, _error_text(result)
        data = _data(result)
        assert data["status"] == "proposed"
        warning = str(data["warning"])
        assert warning == (
            "this will be 161 characters; limit 160, shorten it; "
            "the human will shorten it at review"
        )

    _run(root, body)
    stored = load_inbox(ProjectPaths(root).inbox).proposed()
    assert len(stored) == 1
    assert stored[0].text == text


def test_response_cap_truncates_on_a_line(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)
    path = root / "COSTANZA.md"
    extra = "\n".join(["## NOTES", *["n" * 80 for _ in range(500)], ""])
    path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")

    async def body(client: Client) -> None:
        result = await client.call_tool("costanza_read", {"budget": 100000})
        assert result.is_error is False, _error_text(result)
        data = _data(result)
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        assert len(encoded) <= _RESPONSE_CAP
        assert data["truncated"] is True
        assert str(data["text"]).endswith("\n")

    _run(root, body)


def test_flood_and_concurrent_proposals(invoke: InvokeFn, tmp_path: Path) -> None:
    root = _project(invoke, tmp_path)

    async def body(client: Client) -> None:
        async def one(index: int) -> CallToolResult:
            return await client.call_tool(
                "costanza_propose",
                {"kind": "D", "text": f"flood item {index} stays unique"},
            )

        first = await asyncio.gather(*[one(index) for index in range(5)])
        assert [item.is_error for item in first] == [False, False, False, False, False]

        rest = await asyncio.gather(*[one(index) for index in range(5, 16)])
        errors = [item for item in rest if item.is_error]
        ok = [item for item in rest if not item.is_error]
        assert len(ok) == 5
        assert len(errors) == 6
        assert all("10 proposals per minute" in _error_text(item) for item in errors)

    _run(root, body)
    stored = load_inbox(ProjectPaths(root).inbox).proposed()
    assert len(stored) == 10
    assert len({item.id for item in stored}) == 10
    assert len({item.text for item in stored}) == 10
