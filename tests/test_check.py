from __future__ import annotations

from pathlib import Path

from costanza.constants import MARKER_CANONICAL, skeleton
from tests.helpers import InvokeFn, InvokeResult


def _write(root: Path, text: str) -> None:
    (root / "COSTANZA.md").write_text(text, encoding="utf-8", newline="\n")


def test_check_valid_tiny(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text)
    result: InvokeResult = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0, result.output
    assert "valid" in result.stdout
    assert "238" in result.stdout


def test_check_missing_file(invoke: InvokeFn, tmp_path: Path) -> None:
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 1
    assert "cz init" in result.stderr


def test_check_missing_marker(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    broken = "\n".join(tiny_text.splitlines()[1:]) + "\n"
    _write(tmp_path, broken)
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 3
    assert "CF001" in result.stderr
    assert "line 1" in result.stderr
    assert MARKER_CANONICAL in " ".join(result.stderr.split())


def test_check_duplicate_id(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    broken = tiny_text.replace(
        "D2 services never import routes; all DB access goes through app/db",
        "D1 services never import routes; all DB access goes through app/db",
    )
    _write(tmp_path, broken)
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 3
    assert "CF006" in result.stderr
    assert "line 16" in result.stderr
    assert "D1" in result.stderr
    assert "delete" in result.stderr or "unused" in result.stderr


def test_check_future_version(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text.replace("v1", "v2", 1))
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 3
    assert "CF002" in result.stderr
    assert "version 2" in result.stderr


def test_check_json(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text.replace(MARKER_CANONICAL, "nope"))
    result = invoke(["--root", str(tmp_path), "check", "--json"])
    assert result.exit_code == 3
    assert '"CF001"' in result.stdout
    assert '"line":1' in result.stdout


def test_check_skeleton_warnings_not_errors(invoke: InvokeFn, tmp_path: Path) -> None:
    _write(tmp_path, skeleton("demo"))
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0
    assert "CF017" in result.stderr
    strict = invoke(["--root", str(tmp_path), "check", "--strict"])
    assert strict.exit_code == 3


def test_check_near_budget_w101(invoke: InvokeFn, tmp_path: Path, near_text: str) -> None:
    _write(tmp_path, near_text)
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0
    assert "W101" in result.stderr
    assert "near budget" in result.stderr


def test_check_secret_e010(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    token = "ghp_" + ("a" * 36)
    _write(tmp_path, tiny_text.replace("zero ops", f"zero ops {token}"))
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 3
    assert "E010" in result.stderr
    assert "github_token" in result.stderr
    assert token not in result.stdout + result.stderr
    assert "ghp_…" in result.stderr or "ghp_" in result.stderr


def test_check_secret_allow(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    invoke(["--root", str(tmp_path), "init"])
    token = "ghp_" + ("b" * 36)
    _write(tmp_path, tiny_text.replace("zero ops", f"zero ops {token}"))
    config = tmp_path / ".costanza" / "config.toml"
    body = config.read_text(encoding="utf-8").replace("allow = []", f'allow = ["{token}"]')
    config.write_text(body, encoding="utf-8")
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0
    assert "E010" not in result.stderr


def test_check_missing_file_ref(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text.replace("zero ops", "zero ops [files: app/missing.py]"))
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0
    assert "W103" in result.stderr
    assert "app/missing.py" in result.stderr


def test_check_decision_resembles_rejected(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    text = tiny_text.replace(
        "D1 SQLite, not Postgres -- single node, zero ops",
        "D1 SQLAlchemy -- too heavy here",
    )
    _write(tmp_path, text)
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0
    assert "W110" in result.stderr
    assert "D1" in result.stderr
    assert "X1" in result.stderr


def test_check_old_proposal(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    from datetime import datetime, timedelta, timezone

    from costanza.inbox import Proposal

    _write(tmp_path, tiny_text)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    inbox = tmp_path / ".costanza" / "inbox.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    item = Proposal(id="p1", kind="D", text="waiting", status="proposed", hash="abcd", ts=old, line=1)
    inbox.write_text(item.to_line() + "\n", encoding="utf-8")
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0
    assert "W109" in result.stderr
    assert "p1" in result.stderr


def test_check_stale_synced(invoke: InvokeFn, git_repo: Path) -> None:
    import subprocess

    invoke(["--root", str(git_repo), "init"])
    first = None
    for index in range(3):
        path = git_repo / f"f{index}.txt"
        path.write_text(f"{index}\n", encoding="utf-8")
        subprocess.run(["git", "add", f"f{index}.txt"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", str(index)], cwd=git_repo, check=True, capture_output=True)
        if first is None:
            first = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=git_repo, text=True).strip()
    text = (git_repo / "COSTANZA.md").read_text(encoding="utf-8")
    synced = text.replace("synced: never", f"synced: {first} 2026-01-01")
    (git_repo / "COSTANZA.md").write_text(synced, encoding="utf-8")
    config = git_repo / ".costanza" / "config.toml"
    stale = config.read_text(encoding="utf-8").replace("stale_after = 20", "stale_after = 2")
    config.write_text(stale, encoding="utf-8")
    result = invoke(["--root", str(git_repo), "check"])
    assert result.exit_code == 0, result.output
    assert "W107" in result.stderr


def test_check_fix_normalizes_whitespace(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    messy = tiny_text.replace("\n\n## NOW\n", "\n\n\n## NOW\n")
    _write(tmp_path, messy)
    result = invoke(["--root", str(tmp_path), "check", "--fix"])
    assert result.exit_code == 0, result.output
    from costanza.format import parse, render

    assert (tmp_path / "COSTANZA.md").read_text(encoding="utf-8") == render(parse(tiny_text))


def test_check_json_schema(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    import json

    _write(tmp_path, tiny_text.replace("zero ops", "zero ops [files: nope.py]"))
    result = invoke(["--root", str(tmp_path), "check", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {"tokens", "budget", "errors", "warnings", "findings"} <= set(payload)
    first = payload["findings"][0]
    assert {"code", "severity", "file", "line", "message", "hint"} <= set(first)


def _file_doc(*lines: str) -> str:
    body = "\n".join(lines)
    return (
        f"{MARKER_CANONICAL}\n"
        "# PROJECT: files\n"
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
        f"{body}\n"
        "\n"
        "## REJECTED\n"
        "\n"
        "## RULES\n"
        "\n"
        "## GOTCHAS\n"
        "\n"
        "## OPEN\n"
    )


def _w103_paths(output: str) -> set[str]:
    found: set[str] = set()
    for line in output.splitlines():
        if "W103" not in line:
            continue
        start = line.find("[files: ")
        end = line.find("]", start)
        if start != -1 and end != -1:
            found.add(line[start + len("[files: ") : end])
    return found


def test_check_w103_dot_directory_exists(invoke: InvokeFn, tmp_path: Path) -> None:
    invoke(["--root", str(tmp_path), "init"])
    _write(tmp_path, _file_doc("D1 ledger [files: .costanza/archive/ids]"))
    result = invoke(["--root", str(tmp_path), "check"])
    assert result.exit_code == 0, result.output
    assert "W103" not in result.stderr
    assert ".costanza/archive/ids" not in _w103_paths(result.stderr)


def test_check_w103_tracked_untracked_ignored_glob_slash(
    invoke: InvokeFn, git_repo: Path
) -> None:
    import subprocess

    invoke(["--root", str(git_repo), "init"])
    tracked = git_repo / "app" / "tracked.py"
    untracked = git_repo / "app" / "loose.py"
    ignored = git_repo / "tmp" / "scratch.py"
    folder = git_repo / "app" / "db"
    tracked.parent.mkdir(parents=True)
    folder.mkdir()
    tracked.write_text("x\n", encoding="utf-8")
    untracked.write_text("y\n", encoding="utf-8")
    ignored.parent.mkdir()
    ignored.write_text("z\n", encoding="utf-8")
    (git_repo / ".gitignore").write_text("tmp/\n", encoding="utf-8")
    subprocess.run(["git", "add", "app/tracked.py", ".gitignore"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "track"], cwd=git_repo, check=True)
    _write(
        git_repo,
        _file_doc(
            "D1 tracked [files: app/tracked.py]",
            "D2 untracked [files: app/loose.py]",
            "D3 ignored [files: tmp/scratch.py]",
            "D4 dotdir [files: .costanza/archive/ids]",
            "D5 directory [files: app/db]",
            "D6 missing [files: app/nope.py]",
            "D7 globhit [files: app/*.py]",
            "D8 globmiss [files: missing/*.py]",
            "D9 backslash [files: app\\tracked.py]",
            "D10 escape [files: ../outside.py]",
        ),
    )
    result = invoke(["--root", str(git_repo), "check"])
    warned = _w103_paths(result.stderr + result.stdout)
    assert "app/tracked.py" not in warned
    assert "app/loose.py" not in warned
    assert "tmp/scratch.py" not in warned
    assert ".costanza/archive/ids" not in warned
    assert "app/db" not in warned
    assert "app/*.py" not in warned
    assert "app/nope.py" in warned
    assert "missing/*.py" in warned
    assert r"app\tracked.py" not in warned
    assert "../outside.py" in warned or "CF013" in result.stderr
