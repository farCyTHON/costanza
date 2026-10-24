"""Print one fresh-chat paste: the condition's files, then the task.

The task sentence is taken from bench/PROTOCOL.md. The answer key in
bench/keys/ is never read or printed.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.catalog import FIXTURES, Fixture  # noqa: E402
from bench.make_fixtures import BenchError, build_repo  # noqa: E402
from bench.measure import costanza_text, naive_handoff, source_tree  # noqa: E402

PROTOCOL = ROOT / "bench" / "PROTOCOL.md"


class PromptError(Exception):
    """The paste could not be built."""


def _spec(name: str) -> Fixture:
    for spec in FIXTURES:
        if spec.name == name:
            return spec
    known = ", ".join(spec.name for spec in FIXTURES)
    raise PromptError(f"unknown fixture {name!r}; known: {known}")


def task_wording(fixture: str, number: int) -> str:
    """The Nth `Task:` line under this fixture in PROTOCOL.md. N starts at 1."""
    if number < 1:
        raise PromptError("task number starts at 1")
    lines = PROTOCOL.read_text(encoding="utf-8").splitlines()
    try:
        begin = lines.index("## Tasks") + 1
    except ValueError as exc:
        raise PromptError("PROTOCOL.md has no Tasks section") from exc
    start = None
    for index, line in enumerate(lines[begin:], start=begin):
        if line == f"### {fixture}":
            start = index + 1
            break
    if start is None:
        raise PromptError(f"unknown fixture {fixture!r}")
    found: list[str] = []
    for line in lines[start:]:
        if line.startswith("### ") or line.startswith("## "):
            break
        if line.startswith("Task: "):
            found.append(line.removeprefix("Task: ").strip())
    if number > len(found):
        raise PromptError(f"{fixture} has {len(found)} tasks; task {number} is out of range")
    return found[number - 1]


def _nl(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _context(repo: Path, condition: str) -> str:
    parts = [_nl(source_tree(repo))]
    if condition == "B":
        parts.append("# NAIVE.md\n")
        parts.append(_nl(naive_handoff(repo)))
    elif condition == "C":
        parts.append("# COSTANZA.md\n")
        parts.append(_nl(costanza_text(repo)))
    return "".join(parts)


def render_prompt(fixture: str, condition: str, number: int) -> str:
    """Condition files, then the protocol task sentence. No answer key."""
    label = condition.upper()
    if label not in {"A", "B", "C"}:
        raise PromptError("condition must be A, B, or C")
    wording = task_wording(fixture, number)
    spec = _spec(fixture)
    with tempfile.TemporaryDirectory(prefix="costanza-bench-", ignore_cleanup_errors=True) as tmp:
        repo = Path(tmp) / spec.name
        build_repo(spec, repo)
        context = _context(repo, label)
    return f"{context}\n# Task\n\n{wording}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the paste for one fresh bench chat. Does not print the answer key."
    )
    parser.add_argument("fixture", help="till or slip")
    parser.add_argument("condition", help="A, B, or C")
    parser.add_argument("task", type=int, help="Task number, starting at 1")
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(render_prompt(args.fixture, args.condition, args.task))
    except (PromptError, BenchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
