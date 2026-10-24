"""Bench fixtures, token table, and score threshold."""

from __future__ import annotations

import ast
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from bench.catalog import FIXTURES, SLIP, TILL, final_state, key_text
from bench.make_fixtures import build_repo
from bench.make_prompt import PromptError, render_prompt, task_wording
from bench.measure import format_report, log_entries, measure_rows, write_packets
from bench.score import ScoreError, render_scores

from costanza.tokens import file_tokens

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("ghp_", "sk-", "akia", "begin openssh", "begin rsa", "password", "api_key", "secret")


def _read_tree(root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            found[rel] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return found


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _items(spec_name: str, values: dict[str, str]) -> str:
    spec = next(item for item in FIXTURES if item.name == spec_name)
    return ";".join(f"{item.id}={values[item.id]}" for item in spec.items)


def _write_csv(path: Path, rows: list[str]) -> Path:
    header = (
        "fixture,task,condition,packet,model,run,item_results,"
        "human_corrections,tokens_to_first_correct,reached_correct,notes\n"
    )
    path.write_text(header + "".join(f"{row}\n" for row in rows), encoding="utf-8", newline="\n")
    return path


def test_exported_trees_match_the_catalog() -> None:
    for spec in FIXTURES:
        root = ROOT / "bench" / "fixtures" / spec.name
        assert _read_tree(root) == final_state(spec)
        assert _text(ROOT / "bench" / "keys" / f"{spec.name}.json") == key_text(spec)
        assert not any(path.name == ".git" for path in root.rglob("*"))


def test_phrases_are_placed_on_purpose() -> None:
    for spec in FIXTURES:
        state = final_state(spec)
        readme = state["README.md"]
        messages = "\n".join(commit.message for commit in spec.commits)
        versions = [(path, text) for commit in spec.commits for path, text in commit.files]
        for item in spec.items:
            assert item.phrase not in readme
            assert item.phrase not in messages
            for task in spec.tasks:
                assert item.phrase not in task.prompt
            if item.kind == "hidden":
                assert item.phrase in state["COSTANZA.md"]
                assert not any(item.phrase in text for path, text in versions if path != "COSTANZA.md")
            elif item.kind == "discoverable":
                assert item.phrase in state["COSTANZA.md"]
                assert any(
                    item.phrase in text for path, text in state.items() if path not in {"COSTANZA.md", "README.md"}
                )
            else:
                assert item.phrase not in state["COSTANZA.md"]
                assert any(
                    item.phrase in text for path, text in state.items() if path not in {"COSTANZA.md", "README.md"}
                )


def test_fixtures_name_nobody_and_hold_no_secret() -> None:
    for spec in FIXTURES:
        blob = "\n".join(final_state(spec).values())
        blob += "\n" + "\n".join(commit.message for commit in spec.commits)
        lowered = blob.lower()
        assert "@" not in blob
        for word in FORBIDDEN:
            assert word not in lowered


def test_till_python_parses_and_cli_skips_sqlite() -> None:
    for path, text in final_state(TILL).items():
        if path.endswith(".py"):
            ast.parse(text)
    tree = ast.parse(final_state(TILL)["till/cli.py"])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "sqlite3" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "sqlite3"


def test_slip_routes_do_not_read_files() -> None:
    text = final_state(SLIP)["src/routes.js"]
    assert 'require("fs")' not in text
    assert "readFileSync" not in text
    json.loads(final_state(SLIP)["package.json"])


def test_protocol_lists_every_task_and_scores_controls_apart() -> None:
    text = _text(ROOT / "bench" / "PROTOCOL.md")
    assert "scored separately" in text
    assert "Control items" in text
    for spec in FIXTURES:
        for task in spec.tasks:
            assert task.prompt in text
            assert f"Applicable: {', '.join(task.applicable)}" in text
        for item in spec.items:
            assert f"| {item.id} | {item.kind} | {item.type} |" in text


def test_benchmark_names_the_limits_and_each_item() -> None:
    text = _text(ROOT / "docs" / "BENCHMARK.md")
    lowered = text.lower()
    assert "small sample" in lowered
    assert "invented" in lowered
    assert "one model" in lowered
    assert "5-20%" in text
    assert "control" in lowered
    assert "hidden" in lowered
    assert "discoverable" in lowered
    for spec in FIXTURES:
        for item in spec.items:
            assert f"{spec.name} {item.id} {item.kind}" in text


def test_template_prints_counts_and_no_percentage() -> None:
    report = render_scores(ROOT / "bench" / "results.template.csv")
    assert "%" not in report
    assert "No data rows were scored." in report
    assert "| A | 0 |" in report
    assert "| B | 0 |" in report
    assert "| C | 0 |" in report


def test_small_sample_prints_raw_counts_without_percentages(tmp_path: Path) -> None:
    blank = {
        "D1": "1",
        "D2": "0",
        "R1": "1",
        "D3": "",
        "X1": "0",
        "X2": "",
        "G1": "1",
        "C1": "",
        "C2": "0",
        "C3": "1",
    }
    packed = _items("till", blank)
    path = _write_csv(
        tmp_path / "results.csv",
        [
            f"till,refund,A,source,example-model,1,{packed},1,100,1,",
            f"till,average,A,source,example-model,2,{packed},3,,0,",
        ],
    )
    report = render_scores(path)
    assert "%" not in report
    assert "Percentages withheld for:" in report
    assert "| A | 2 | 2 | 2 | 4 | 4 | 2 | 0 | 2 | 2 | 2 | 2 | 2 | 4 | 2.00 | 100 | 1 | 100.00 | 1 |" in report
    assert "| B | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 | 0 | - | 0 |" in report
    assert "| A | till | D2 | discoverable | 0 | 2 | 0 |" in report


def test_thirty_rows_may_print_percentages(tmp_path: Path) -> None:
    packed = _items("till", {item.id: "1" for item in TILL.items})
    rows = [f"till,refund,C,source+costanza,example-model,{index},{packed},0,10,1," for index in range(1, 31)]
    report = render_scores(_write_csv(tmp_path / "results.csv", rows))
    assert "## Rates" in report
    assert "100%" in report
    assert "Percentages withheld for: A (n=0), B (n=0)." in report


def test_score_rejects_a_guessed_token_and_a_partial_key(tmp_path: Path) -> None:
    packed = _items("slip", {item.id: "1" for item in SLIP.items})
    bad_tokens = _write_csv(tmp_path / "tokens.csv", [f"slip,phone,A,source,example-model,1,{packed},1,40,0,"])
    with pytest.raises(ScoreError, match="leave tokens blank"):
        render_scores(bad_tokens)
    partial = packed.replace("C3=1", "")
    bad_items = _write_csv(tmp_path / "items.csv", [f"slip,phone,A,source,example-model,1,{partial},0,,0,"])
    with pytest.raises(ScoreError, match="missing"):
        render_scores(bad_items)
    bad_packet = _write_csv(tmp_path / "packet.csv", [f"slip,phone,C,source,example-model,1,{packed},0,,0,"])
    with pytest.raises(ScoreError, match="packet"):
        render_scores(bad_packet)


def test_rebuilt_history_drops_the_two_oldest_commits(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    for spec in FIXTURES:
        repo = tmp_path / spec.name
        build_repo(spec, repo)
        counted = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert int(counted.stdout.strip()) == 22
        blob = "\n".join(log_entries(repo))
        assert spec.commits[0].message not in blob
        assert spec.commits[1].message not in blob
        assert spec.commits[2].message in blob
        assert spec.commits[-1].message in blob


def test_measure_matches_the_published_report() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    rows = measure_rows()
    report = format_report(rows)
    assert report == format_report(measure_rows())
    assert report in _text(ROOT / "docs" / "BENCHMARK.md")
    for row in rows:
        assert row.costanza > 0
        assert row.source > row.costanza
        assert row.source > row.naive
        assert row.condition_a == row.source
        assert row.condition_b == row.source + row.naive
        assert row.condition_c == row.source + row.costanza


def test_packets_keep_hidden_items_out_of_a_and_b(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    write_packets(tmp_path)
    till = tmp_path / "till"
    pieces = [path.read_text(encoding="utf-8") for path in (till / "A").rglob("*") if path.is_file()]
    joined = "\n".join(pieces)
    assert "integer cents" in joined
    assert "half-up" in joined
    assert "SQLAlchemy" not in joined
    def listed(folder: Path) -> dict[str, str]:
        return {
            path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
            for path in folder.rglob("*")
            if path.is_file()
        }

    source_a = listed(till / "A")
    source_b = listed(till / "B")
    source_c = listed(till / "C")
    naive = source_b.pop("NAIVE.md")
    handoff = source_c.pop("COSTANZA.md")
    assert "NAIVE.md" not in source_a
    assert "COSTANZA.md" not in source_a
    assert source_b == source_a
    assert source_c == source_a
    assert "DRAWERZERO" not in naive
    assert "SQLAlchemy" not in naive
    assert "integer cents" not in naive
    assert "SQLAlchemy" in handoff
    assert "half-up" not in handoff
    measured = {row.name: row for row in measure_rows()}
    assert file_tokens(naive) == measured["till"].naive


def test_node_files_parse_when_node_is_installed() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    root = ROOT / "bench" / "fixtures" / "slip"
    for path in root.rglob("*.js"):
        proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, proc.stderr


def test_template_header_matches_the_scorer() -> None:
    with (ROOT / "bench" / "results.template.csv").open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header[:10] == [
        "fixture",
        "task",
        "condition",
        "packet",
        "model",
        "run",
        "item_results",
        "human_corrections",
        "tokens_to_first_correct",
        "reached_correct",
    ]


def _protocol_tasks(fixture: str) -> list[str]:
    text = _text(ROOT / "bench" / "PROTOCOL.md").split("## Tasks\n", 1)[1]
    section = text.split(f"### {fixture}\n", 1)[1]
    section = section.split("\n## ", 1)[0]
    return [line.removeprefix("Task: ").strip() for line in section.splitlines() if line.startswith("Task: ")]


def test_task_wording_is_the_protocol_line() -> None:
    assert task_wording("till", 1) == _protocol_tasks("till")[0]
    assert task_wording("till", 2) == _protocol_tasks("till")[1]
    assert task_wording("slip", 5) == _protocol_tasks("slip")[4]
    assert "make_prompt.py" in _text(ROOT / "bench" / "PROTOCOL.md")
    with pytest.raises(PromptError, match="out of range"):
        task_wording("till", 99)
    with pytest.raises(PromptError, match="unknown fixture"):
        task_wording("nope", 1)
    with pytest.raises(PromptError, match="condition"):
        render_prompt("till", "D", 1)


def test_make_prompt_pastes_the_condition_then_the_task() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    wording = task_wording("till", 1)
    ending = f"\n# Task\n\n{wording}\n"
    alone = render_prompt("till", "A", 1)
    naive = render_prompt("till", "B", 1)
    handed = render_prompt("till", "C", 1)
    for prompt in (alone, naive, handed):
        assert prompt.endswith(ending)
        assert "Applicable:" not in prompt
        assert "bench/keys" not in prompt
        assert "what the scorer checks" not in prompt
        assert '"phrase"' not in prompt
    assert "integer cents" in alone
    assert "half-up" in alone
    assert "SQLAlchemy" not in alone
    assert "database path flag" not in alone
    assert "# NAIVE.md" not in alone
    assert "# COSTANZA.md" not in alone
    assert "# NAIVE.md" in naive
    assert "SQLAlchemy" not in naive
    assert "DRAWERZERO" not in naive
    assert "clarify the drawer module notes" in naive
    assert naive.index("# NAIVE.md") < naive.index("\n# Task\n")
    assert "# COSTANZA.md" in handed
    assert "SQLAlchemy" in handed
    assert handed.index("# COSTANZA.md") < handed.index("\n# Task\n")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bench" / "make_prompt.py"), "till", "A", "1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == alone


def test_score_cli_rejects_a_missing_file() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bench" / "score.py"), str(ROOT / "bench" / "no-such-results.csv")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 2
    assert "Do not invent rows." in proc.stderr
