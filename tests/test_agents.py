from __future__ import annotations

from pathlib import Path

from costanza.agents import install_agents, remove_agents, status_agents
from costanza.constants import AGENT_BLOCK, MCP_PROPOSE_DESCRIPTION, MDC_FRONTMATTER
from tests.helpers import InvokeFn

FIXTURES = Path(__file__).parent / "fixtures" / "agents"


def _seed(root: Path, name: str, dest: str | None = None) -> Path:
    src = FIXTURES / name
    target = root / (dest or name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(src.read_bytes())
    return target


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--agents", "none"])
    assert result.exit_code == 0, result.output


def test_block_under_120_words() -> None:
    body = AGENT_BLOCK.split("<!-- costanza:begin v1 -->", 1)[1]
    body = body.split("<!-- costanza:end -->", 1)[0]
    assert len(body.split()) <= 120


def test_block_is_imperative_and_covers_required_points() -> None:
    text = AGENT_BLOCK
    assert "Read COSTANZA.md fully before acting." in text
    assert "It is the project state." in text
    assert "Never search outside the project folder." in text
    assert "Obey RULES." in text
    assert "Never contradict DECISIONS." in text
    assert "Never re-suggest REJECTED" in text
    assert "costanza_propose" in text
    assert "costanza decide" in text
    assert "fenced costanza block" in text
    assert "Update NOW" in text
    assert "Never include secrets." in text
    assert "Never edit the decision sections directly." in text
    assert "One line per entry, at most 130 characters." in text
    assert MCP_PROPOSE_DESCRIPTION == (
        "Propose one entry. Entries are one line of at most 130 characters."
    )


def test_insert_update_remove_idempotent_on_each_target(tmp_path: Path) -> None:
    _init_via_files = tmp_path
    (tmp_path / "COSTANZA.md").write_text("# PROJECT: t\n", encoding="utf-8")
    (tmp_path / ".costanza").mkdir()
    cases = [
        ("CLAUDE.md", "claude-before.md", "claude-inserted.md"),
        ("GEMINI.md", "gemini-before.md", None),
        (".github/copilot-instructions.md", "copilot-before.md", None),
    ]
    for dest, before, golden in cases:
        path = _seed(tmp_path, before, dest)
        original = path.read_bytes()
        first = install_agents(mode="auto", targets=[path], explicit=tmp_path)
        assert first.rows[0].status in {"installed", "created"}
        assert first.rows[0].written
        if golden is not None:
            assert path.read_text(encoding="utf-8") == (FIXTURES / golden).read_text(encoding="utf-8")
        inside = path.read_bytes()
        assert b"<!-- costanza:begin v1 -->" in inside
        prefix = original.decode("utf-8").split("<!--")[0]
        assert prefix.replace("\r\n", "\n").rstrip() in path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime_ns
        second = install_agents(mode="auto", targets=[path], explicit=tmp_path)
        assert second.rows[0].status == "unchanged"
        assert not second.rows[0].written
        assert path.stat().st_mtime_ns == mtime
        assert path.read_bytes() == inside
        removed = remove_agents(targets=[path], explicit=tmp_path)
        assert removed.rows[0].status == "removed"
        assert path.read_bytes() == original
    _ = _init_via_files


def test_v0_replaced_in_place(tmp_path: Path) -> None:
    path = _seed(tmp_path, "v0-before.md", "NOTES.md")
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    result = install_agents(targets=[path], explicit=tmp_path)
    assert result.rows[0].status == "installed"
    assert path.read_text(encoding="utf-8") == (FIXTURES / "v0-updated.md").read_text(encoding="utf-8")


def test_crlf_and_outside_bytes_preserved(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    prefix = "# Claude\r\nkeep me\r\n"
    path = tmp_path / "CLAUDE.md"
    path.write_bytes(prefix.encode("utf-8"))
    install_agents(targets=[path], explicit=tmp_path)
    data = path.read_bytes()
    assert b"\r\n" in data
    assert data.startswith(prefix.encode("utf-8") + b"\r\n")
    assert b"keep me" in data
    assert data.count(b"<!-- costanza:begin v1 -->") == 1
    before = data
    mtime = path.stat().st_mtime_ns
    again = install_agents(targets=[path], explicit=tmp_path)
    assert again.rows[0].status == "unchanged"
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    remove_agents(targets=[path], explicit=tmp_path)
    assert path.read_bytes() == prefix.encode("utf-8")


def test_bom_preserved(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    path = tmp_path / "GEMINI.md"
    path.write_bytes(b"\xef\xbb\xbf# Gemini\nnotes\n")
    install_agents(targets=[path], explicit=tmp_path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert path.read_bytes().count(b"\xef\xbb\xbf") == 1
    remove_agents(targets=[path], explicit=tmp_path)
    assert path.read_bytes() == b"\xef\xbb\xbf# Gemini\nnotes\n"


def test_unbalanced_markers_are_left_alone(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    path = tmp_path / "CLAUDE.md"
    path.write_text("<!-- costanza:begin v1 -->\nno end\n", encoding="utf-8")
    before = path.read_bytes()
    result = install_agents(targets=[path], explicit=tmp_path)
    assert result.failed
    assert result.rows[0].status == "failed"
    assert path.read_bytes() == before


def test_newer_block_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    path = tmp_path / "CLAUDE.md"
    path.write_text("<!-- costanza:begin v2 -->\nfuture\n<!-- costanza:end -->\n", encoding="utf-8")
    before = path.read_bytes()
    result = install_agents(targets=[path], explicit=tmp_path)
    assert result.failed
    assert result.rows[0].status == "newer"
    assert path.read_bytes() == before


def test_mdc_golden_and_remove_deletes_ours(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    (tmp_path / ".cursor").mkdir()
    install_agents(mode="auto", explicit=tmp_path)
    mdc = tmp_path / ".cursor" / "rules" / "costanza.mdc"
    assert mdc.is_file()
    assert mdc.read_text(encoding="utf-8") == (FIXTURES / "mdc-created.mdc").read_text(encoding="utf-8")
    assert mdc.read_text(encoding="utf-8").startswith(MDC_FRONTMATTER)
    remove_agents(mode="auto", explicit=tmp_path)
    assert not mdc.exists()


def test_auto_creates_agents_md_only(invoke: InvokeFn, tmp_path: Path) -> None:
    result = invoke(["--root", str(tmp_path), "init", "--agents", "auto"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "AGENTS.md").is_file()
    assert AGENT_BLOCK.strip() in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "GEMINI.md").exists()
    assert not (tmp_path / ".github" / "copilot-instructions.md").exists()


def test_all_creates_every_target(invoke: InvokeFn, tmp_path: Path) -> None:
    result = invoke(["--root", str(tmp_path), "init", "--agents", "all"])
    assert result.exit_code == 0, result.output
    for relative in (
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        ".cursor/rules/costanza.mdc",
        ".github/copilot-instructions.md",
    ):
        assert (tmp_path / relative).is_file(), relative


def test_none_creates_no_agent_files(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init", "--agents", "none"])
    assert not (tmp_path / "AGENTS.md").exists()


def test_cli_install_remove_status(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init", "--agents", "none"])
    (tmp_path / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    installed = invoke(["--root", str(tmp_path), "agents", "install", "--mode", "auto"])
    assert installed.exit_code == 0, installed.output
    assert "AGENTS.md" in installed.stdout
    assert "CLAUDE.md" in installed.stdout
    status = invoke(["--root", str(tmp_path), "agents", "status"])
    assert status.exit_code == 0
    removed = invoke(["--root", str(tmp_path), "agents", "--remove"])
    assert removed.exit_code == 0, removed.output
    assert not (tmp_path / "AGENTS.md").exists()
    assert "<!-- costanza:begin" not in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_case_preserving_claude_md(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    path = tmp_path / "Claude.md"
    path.write_text("# Claude\n", encoding="utf-8")
    install_agents(mode="auto", explicit=tmp_path)
    names = {item.name for item in tmp_path.iterdir()}
    if "Claude.md" in names:
        assert "CLAUDE.md" not in names or path.exists()
    assert b"<!-- costanza:begin v1 -->" in path.read_bytes() or any(
        child.name.lower() == "claude.md" and b"costanza:begin" in child.read_bytes()
        for child in tmp_path.iterdir()
        if child.is_file()
    )


def test_status_reports_installed(tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x\n", encoding="utf-8")
    install_agents(mode="all", explicit=tmp_path)
    result = status_agents(mode="all", explicit=tmp_path)
    statuses = {row.path: row.status for row in result.rows}
    assert statuses["AGENTS.md"] == "installed"
    assert statuses["CLAUDE.md"] == "installed"
