from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from costanza.format import ENTRY_LINE_RE, parse
from costanza.inbox import Proposal, utc_now
from tests.helpers import InvokeFn

FIXTURES = Path(__file__).parent / "fixtures"


def _entries(text: str) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        match = ENTRY_LINE_RE.match(line.strip())
        if match:
            found.add(f"{match.group(1)}{match.group(2)}")
    return found


def test_compact_dry_run_default(invoke: InvokeFn, tmp_path: Path, near_text: str) -> None:
    (tmp_path / "COSTANZA.md").write_text(near_text, encoding="utf-8")
    result = invoke(["--root", str(tmp_path), "compact"])
    assert result.exit_code == 0, result.output
    assert "would move" in result.stdout
    assert "G2" in result.stdout
    assert (tmp_path / "COSTANZA.md").read_text(encoding="utf-8") == near_text


def test_compact_apply_order_and_lossless(invoke: InvokeFn, tmp_path: Path, near_text: str) -> None:
    (tmp_path / "COSTANZA.md").write_text(near_text, encoding="utf-8")
    before = _entries(near_text)
    result = invoke(["--root", str(tmp_path), "compact", "--apply"])
    assert result.exit_code == 0, result.output
    assert "G2 G3 G5 G6 G7 G8" in result.stdout
    file_text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    document = parse(file_text)
    assert [item.id for item in document.rules]
    assert [item.id for item in document.open]
    moved = {"G2", "G3", "G5", "G6", "G7", "G8"}
    assert moved.isdisjoint(_entries(file_text))
    archive_dir = tmp_path / ".costanza" / "archive"
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    archive = archive_dir / f"{month}.md"
    assert archive.is_file()
    archive_text = archive.read_text(encoding="utf-8")
    assert "## " in archive_text and "compact" in archive_text
    assert _entries(file_text) | _entries(archive_text) == before
    assert "archive: .costanza/archive/" in file_text
    assert "R1" in file_text
    assert "Q1" in file_text


def test_compact_never_moves_rules_or_questions(invoke: InvokeFn, tmp_path: Path) -> None:
    from costanza.constants import MARKER_CANONICAL

    text = (
        f"{MARKER_CANONICAL}\n"
        "# PROJECT: only-rules\n"
        "stack: x\n"
        "run: x | test: x\n"
        "layout: x\n"
        "synced: never\n"
        "\n"
        "## NOW\n"
        "doing: none\n"
        "done: none\n"
        "next: none\n"
        "blocked: none\n"
        "\n"
        "## DECISIONS\n"
        "\n"
        "## REJECTED\n"
        "\n"
        "## RULES\n"
        + "\n".join(f"R{n} keep this rule number {n} and some padding words here" for n in range(1, 40))
        + "\n\n## GOTCHAS\n\n## OPEN\n"
        + "\n".join(f"Q{n} still open question {n} with extra words" for n in range(1, 20))
        + "\n"
    )
    invoke(["--root", str(tmp_path), "init"])
    (tmp_path / "COSTANZA.md").write_text(text, encoding="utf-8")
    config = tmp_path / ".costanza" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("tokens = 1800", "tokens = 400"),
        encoding="utf-8",
    )
    result = invoke(["--root", str(tmp_path), "compact", "--apply"])
    assert result.exit_code == 3, result.output
    after = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "R1" in after
    assert "Q1" in after
    assert "still over budget" in result.stderr


def test_compact_inbox_moves_old_decided(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])
    old = (datetime.now(timezone.utc) - timedelta(days=100)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    inbox = tmp_path / ".costanza" / "inbox.jsonl"
    kept = Proposal(id="p1", kind="D", text="open", status="proposed", hash="aaaa", ts=utc_now())
    moved = Proposal(
        id="p2",
        kind="D",
        text="done",
        status="accepted",
        hash="bbbb",
        decided=old,
        ts=old,
    )
    junk = '{"not": "valid"'
    inbox.write_text(kept.to_line() + "\n" + moved.to_line() + "\n" + junk + "\n", encoding="utf-8")
    dry = invoke(["--root", str(tmp_path), "compact", "--inbox"])
    assert dry.exit_code == 0
    assert inbox.read_text(encoding="utf-8").count("p2") == 1
    applied = invoke(["--root", str(tmp_path), "compact", "--inbox", "--apply"])
    assert applied.exit_code == 0, applied.output
    live = inbox.read_text(encoding="utf-8")
    assert "p1" in live
    assert "p2" not in live
    assert junk in live
    archived = (tmp_path / ".costanza" / "inbox-archive.jsonl").read_text(encoding="utf-8")
    assert "p2" in archived
    assert "p1" not in archived


def test_compact_names_target_not_budget(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])
    result = invoke(["--root", str(tmp_path), "compact"])
    assert result.exit_code == 0, result.output
    assert "target 1,530 = 85% of 1,800" in result.stdout
    assert "1,800" in result.stdout


def test_compact_inbox_flag_errors(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])
    bad = invoke(["--root", str(tmp_path), "compact", "--purge"])
    assert bad.exit_code == 2
    bad_target = invoke(["--root", str(tmp_path), "compact", "--inbox", "--target", "10"])
    assert bad_target.exit_code == 2
