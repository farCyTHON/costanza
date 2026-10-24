"""Count handoff tokens for the two bench fixtures.

No network. The count is Costanza's built-in estimate, not a tokenizer.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _entry in (SRC, ROOT):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from bench.catalog import FIXTURES, Fixture  # noqa: E402
from bench.make_fixtures import BenchError, build_repo  # noqa: E402
from costanza.tokens import file_tokens  # noqa: E402


def project_files(repo: Path) -> list[str]:
    """Sorted project paths, skipping a nested git directory."""
    found: list[str] = []
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo)
        if ".git" in rel.parts:
            continue
        found.append(rel.as_posix())
    return sorted(found)


def log_entries(repo: Path) -> list[str]:
    """Last 20 commits as YYYY-MM-DD plus the subject.

    The date is the author date stored on the commit (UTC in these
    fixtures), not the machine's local zone. Hashes are omitted so the
    token count does not depend on hash abbreviation.
    """
    git = shutil.which("git")
    if git is None:
        raise BenchError("git is not on PATH")
    proc = subprocess.run(
        [git, "-c", "core.quotepath=false", "log", "-20", "--pretty=format:%aI%x09%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise BenchError(f"git log failed: {detail}")
    lines: list[str] = []
    for raw in proc.stdout.splitlines():
        iso, subject = raw.split("\t", 1)
        lines.append(f"{iso[:10]} {subject}")
    if len(lines) != 20:
        raise BenchError(f"expected 20 log entries, got {len(lines)}")
    return lines


def costanza_text(repo: Path) -> str:
    return (repo / "COSTANZA.md").read_text(encoding="utf-8")


def naive_handoff(repo: Path) -> str:
    """README, a file tree, and the last 20 commit subjects."""
    readme = (repo / "README.md").read_text(encoding="utf-8")
    if not readme.endswith("\n"):
        readme += "\n"
    tree = "\n".join(project_files(repo)) + "\n"
    log = "\n".join(log_entries(repo)) + "\n"
    return f"# README\n\n{readme}\n# Files\n\n{tree}\n# Recent commits\n\n{log}"


def source_tree(repo: Path) -> str:
    """Every project file except COSTANZA.md, prefixed with its path."""
    parts: list[str] = []
    for rel in project_files(repo):
        if rel == "COSTANZA.md":
            continue
        text = (repo / rel).read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        parts.append(f"# {rel}\n{text}")
    return "\n".join(parts)


def _ending_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


class MeasureRow(NamedTuple):
    name: str
    costanza: int
    naive: int
    source: int
    condition_a: int
    condition_b: int
    condition_c: int


def _with_repo(spec: Fixture) -> tuple[str, str, str]:
    with tempfile.TemporaryDirectory(prefix="costanza-bench-", ignore_cleanup_errors=True) as tmp:
        repo = Path(tmp) / spec.name
        build_repo(spec, repo)
        return costanza_text(repo), naive_handoff(repo), source_tree(repo)


def measure_rows() -> list[MeasureRow]:
    """Token estimates for the parts and for conditions A, B, and C.

    A, B, and C each include the same source text. B appends the naive
    handoff. C appends COSTANZA.md. The texts are joined with LF.
    """
    rows: list[MeasureRow] = []
    for spec in FIXTURES:
        handoff, naive, source = _with_repo(spec)
        source_text = _ending_newline(source)
        rows.append(
            MeasureRow(
                spec.name,
                file_tokens(handoff),
                file_tokens(naive),
                file_tokens(source),
                file_tokens(source_text),
                file_tokens(source_text + _ending_newline(naive)),
                file_tokens(source_text + _ending_newline(handoff)),
            )
        )
    return rows


def format_report(rows: list[MeasureRow]) -> str:
    lines = [
        "Estimator: Costanza estimate (file_tokens in src/costanza/tokens.py).",
        "This is a heuristic, not a BPE tokenizer. On English-heavy text it tends to",
        "overestimate cl100k_base and o200k_base by about 5-20%, and it can underestimate",
        "CJK. These fixtures are English. This run did not compare the heuristic with",
        "tiktoken; that band is the documented expectation, not a measurement from this bench.",
        "",
        "Naive handoff: README.md, then a sorted file tree, then the last 20 commits as",
        "YYYY-MM-DD and subject (git log -20 --pretty=format:%aI %s, date taken from the",
        "recorded author time). Short hashes are not included.",
        "Source tree: every file except COSTANZA.md, sorted by path, each prefixed with",
        'a "# path" line, joined with LF. COSTANZA.md is excluded so this column is the',
        "code and README, not the handoff.",
        "A, B, and C each start from that same source text. A is the source alone.",
        "B appends the naive handoff. C appends COSTANZA.md. The parts are joined with LF.",
        "",
        "| fixture | COSTANZA.md | naive handoff | source tree | A | B | C |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.name} | {row.costanza} | {row.naive} | {row.source} "
            f"| {row.condition_a} | {row.condition_b} | {row.condition_c} |"
        )
    adds = all(
        row.condition_a == row.source
        and row.condition_b == row.source + row.naive
        and row.condition_c == row.source + row.costanza
        for row in rows
    )
    lines.append("")
    if adds:
        lines.append(
            "On this run the condition columns add: A equals the source column, "
            "B equals source plus naive, and C equals source plus COSTANZA.md."
        )
    else:
        lines.append(
            "On this run the condition columns are not the sum of the part columns. "
            "Use the A, B, and C figures."
        )
    lines.append("")
    return "\n".join(lines)


def render_measure() -> str:
    return format_report(measure_rows())


def _write_source(repo: Path, dest: Path) -> None:
    """Copy the project files except COSTANZA.md."""
    for rel in project_files(repo):
        if rel == "COSTANZA.md":
            continue
        text = (repo / rel).read_text(encoding="utf-8")
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def write_packets(dest: Path) -> None:
    """Write A, B, and C folders with the same source tree.

    COSTANZA.md is not part of that tree. B also contains NAIVE.md.
    C also contains COSTANZA.md.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for spec in FIXTURES:
        with tempfile.TemporaryDirectory(prefix="costanza-bench-", ignore_cleanup_errors=True) as tmp:
            repo = Path(tmp) / spec.name
            build_repo(spec, repo)
            target = dest / spec.name
            if target.exists():
                shutil.rmtree(target)
            for label in ("A", "B", "C"):
                _write_source(repo, target / label)
            (target / "B" / "NAIVE.md").write_text(naive_handoff(repo), encoding="utf-8", newline="\n")
            (target / "C" / "COSTANZA.md").write_text(costanza_text(repo), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count handoff tokens for the bench fixtures.")
    parser.add_argument(
        "--packets",
        type=Path,
        help="Also write condition A/B/C packets into this directory. No model is called.",
    )
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(render_measure())
        if args.packets is not None:
            write_packets(args.packets)
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
