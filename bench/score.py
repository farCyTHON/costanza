"""Aggregate a filled bench results CSV.

Always prints raw counts and n. Prints percentages only when a condition
has at least MIN_PERCENT_ROWS rows. Below that, a percentage looks sharper
than one sitting on two invented projects can support.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

MIN_PERCENT_ROWS = 30
REQUIRED = (
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
)
# What each condition is given, besides the task text. The source tree
# never includes COSTANZA.md. B and C add one file to that same tree.
CONDITION_PACKETS = {
    "A": "source",
    "B": "source+naive",
    "C": "source+costanza",
}
SUMMARY_COLUMNS = (
    "condition",
    "n",
    "hidden followed",
    "hidden missed",
    "hidden n/a",
    "discoverable followed",
    "discoverable missed",
    "discoverable n/a",
    "control followed",
    "control missed",
    "control n/a",
    "decisions contradicted",
    "rejected re-suggested",
    "corrections sum",
    "corrections mean",
    "tokens sum",
    "tokens n",
    "tokens mean",
    "reached correct",
)
CUTOFF = (
    f"Rates are shown only for a condition with at least {MIN_PERCENT_ROWS} rows. "
    "Below that, a percentage looks sharper than these rows can support: the tasks "
    "are related, the projects are invented, and a sitting is usually one model."
)


class ScoreError(Exception):
    """The CSV could not be scored. Nothing was invented to fill the gap."""


@dataclass(frozen=True)
class KeyItem:
    id: str
    kind: str
    type: str


@dataclass
class Run:
    fixture: str
    task: str
    condition: str
    model: str
    run: str
    items: dict[str, int | None]
    corrections: int
    tokens: int | None
    reached: int


@dataclass
class Totals:
    n: int = 0
    hidden: list[int] = field(default_factory=lambda: [0, 0, 0])
    discoverable: list[int] = field(default_factory=lambda: [0, 0, 0])
    control: list[int] = field(default_factory=lambda: [0, 0, 0])
    contradicted: int = 0
    resuggested: int = 0
    corrections: int = 0
    tokens_sum: int = 0
    tokens_n: int = 0
    reached: int = 0
    models: set[str] = field(default_factory=set)
    per_item: dict[tuple[str, str], list[int]] = field(default_factory=dict)


def load_keys(keys_dir: Path) -> dict[str, dict[str, KeyItem]]:
    if not keys_dir.is_dir():
        raise ScoreError(f"missing answer keys at {keys_dir}; run python bench/make_fixtures.py")
    found: dict[str, dict[str, KeyItem]] = {}
    for path in sorted(keys_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        name = str(data["fixture"])
        items: dict[str, KeyItem] = {}
        for raw in data["items"]:
            items[str(raw["id"])] = KeyItem(str(raw["id"]), str(raw["kind"]), str(raw["type"]))
        if not items:
            raise ScoreError(f"{path} has no items")
        found[name] = items
    if not found:
        raise ScoreError(f"no answer keys in {keys_dir}")
    return found


def _parse_items(text: str) -> dict[str, int | None]:
    if text.strip() == "":
        raise ScoreError("item_results is empty")
    found: dict[str, int | None] = {}
    for part in text.split(";"):
        piece = part.strip()
        if piece == "":
            continue
        if "=" not in piece:
            raise ScoreError(f"bad item result {piece!r}")
        ident, raw = piece.split("=", 1)
        ident = ident.strip()
        raw = raw.strip()
        if ident in found:
            raise ScoreError(f"duplicate item {ident}")
        if raw == "":
            found[ident] = None
        elif raw in {"0", "1"}:
            found[ident] = int(raw)
        else:
            raise ScoreError(f"item {ident} must be 1, 0, or blank")
    return found


def _nonneg(label: str, raw: str, *, allow_blank: bool) -> int | None:
    text = raw.strip()
    if text == "" and allow_blank:
        return None
    if text == "" or not text.isdigit():
        raise ScoreError(f"{label} must be a non-negative integer")
    return int(text)


def load_runs(csv_path: Path, keys: dict[str, dict[str, KeyItem]]) -> list[Run]:
    try:
        text = csv_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ScoreError(str(exc)) from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ScoreError("CSV header is missing")
    missing = [name for name in REQUIRED if name not in reader.fieldnames]
    if missing:
        raise ScoreError("CSV is missing columns: " + ", ".join(missing))
    runs: list[Run] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for number, row in enumerate(reader, start=2):
        if all(not (row.get(name) or "").strip() for name in REQUIRED):
            continue
        fixture = (row.get("fixture") or "").strip()
        task = (row.get("task") or "").strip()
        condition = (row.get("condition") or "").strip()
        packet = (row.get("packet") or "").strip()
        model = (row.get("model") or "").strip()
        run_id = (row.get("run") or "").strip()
        if not all((fixture, task, condition, model, run_id)):
            raise ScoreError(f"line {number} has an empty fixture, task, condition, model, or run")
        expected_packet = CONDITION_PACKETS.get(condition)
        if expected_packet is not None and packet != expected_packet:
            raise ScoreError(
                f"line {number} condition {condition} must use packet {expected_packet!r}, got {packet!r}"
            )
        if expected_packet is None and packet == "":
            raise ScoreError(f"line {number} needs a packet value")
        if fixture not in keys:
            known = ", ".join(sorted(keys))
            raise ScoreError(f"line {number} has unknown fixture {fixture!r}; known: {known}")
        identity = (fixture, task, condition, model, run_id)
        if identity in seen:
            raise ScoreError(f"line {number} repeats {fixture}/{task}/{condition}/{model}/{run_id}")
        seen.add(identity)
        items = _parse_items(row.get("item_results") or "")
        expected = set(keys[fixture])
        if set(items) != expected:
            missing_ids = ", ".join(sorted(expected - set(items)))
            extra_ids = ", ".join(sorted(set(items) - expected))
            raise ScoreError(f"line {number} item_results missing [{missing_ids}] extra [{extra_ids}]")
        corrections = _nonneg("human_corrections", row.get("human_corrections") or "", allow_blank=False)
        tokens = _nonneg("tokens_to_first_correct", row.get("tokens_to_first_correct") or "", allow_blank=True)
        reached = _nonneg("reached_correct", row.get("reached_correct") or "", allow_blank=False)
        if corrections is None or reached is None or reached not in {0, 1}:
            raise ScoreError(f"line {number} reached_correct must be 0 or 1")
        if reached == 0 and tokens is not None:
            raise ScoreError(
                f"line {number} has a token count but reached_correct is 0; "
                "leave tokens blank rather than estimate"
            )
        runs.append(
            Run(
                fixture=fixture,
                task=task,
                condition=condition,
                model=model,
                run=run_id,
                items=items,
                corrections=corrections,
                tokens=tokens,
                reached=reached,
            )
        )
    return runs


def _bucket(totals: Totals, kind: str) -> list[int]:
    if kind == "hidden":
        return totals.hidden
    if kind == "discoverable":
        return totals.discoverable
    if kind == "control":
        return totals.control
    raise ScoreError(f"unknown item kind {kind!r}")


def summarize(runs: list[Run], keys: dict[str, dict[str, KeyItem]]) -> dict[str, Totals]:
    names = {run.condition for run in runs}
    ordered = ["A", "B", "C"]
    ordered.extend(sorted(names - {"A", "B", "C"}))
    totals = {name: Totals() for name in ordered}
    for run in runs:
        bucket = totals[run.condition]
        bucket.n += 1
        bucket.corrections += run.corrections
        bucket.reached += run.reached
        bucket.models.add(run.model)
        if run.tokens is not None:
            bucket.tokens_sum += run.tokens
            bucket.tokens_n += 1
        for item_id, value in run.items.items():
            item = keys[run.fixture][item_id]
            counts = _bucket(bucket, item.kind)
            cell = bucket.per_item.setdefault((run.fixture, item_id), [0, 0, 0])
            if value is None:
                slot = 2
            elif value == 1:
                slot = 0
            else:
                slot = 1
            counts[slot] += 1
            cell[slot] += 1
            if item.type == "decision" and value == 0:
                bucket.contradicted += 1
            if item.type == "rejected" and value == 0:
                bucket.resuggested += 1
    return totals


def _mean(total: int, count: int) -> str:
    if count == 0:
        return "-"
    return f"{total / count:.2f}"


def _percent(followed: int, missed: int) -> str:
    applicable = followed + missed
    if applicable == 0:
        return "-"
    return f"{(100 * followed + applicable // 2) // applicable}%"


def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def format_report(totals: dict[str, Totals], keys: dict[str, dict[str, KeyItem]]) -> str:
    models = sorted({model for bucket in totals.values() for model in bucket.models})
    lines = [
        "# Scores",
        "",
        "n is the number of CSV rows in that condition. One row is one task, one condition, one run.",
        "A is the source tree with COSTANZA.md removed. B is that same tree plus the naive handoff.",
        "C is that same tree plus COSTANZA.md.",
        "Hidden and discoverable items are the seeded set. Control items are scored separately",
        "and are not added into the seeded counts.",
        "",
        CUTOFF,
        "",
        "Models in this file: " + (", ".join(models) if models else "none") + ".",
    ]
    if len(models) > 1:
        lines.append("This file mixes models. Do not read a condition mean as one model's score.")
    if sum(bucket.n for bucket in totals.values()) == 0:
        lines.append("No data rows were scored.")
    lines.extend(["", _md_row(list(SUMMARY_COLUMNS)), _md_row(["---"] * len(SUMMARY_COLUMNS))])
    for name, bucket in totals.items():
        lines.append(
            _md_row(
                [
                    name,
                    str(bucket.n),
                    str(bucket.hidden[0]),
                    str(bucket.hidden[1]),
                    str(bucket.hidden[2]),
                    str(bucket.discoverable[0]),
                    str(bucket.discoverable[1]),
                    str(bucket.discoverable[2]),
                    str(bucket.control[0]),
                    str(bucket.control[1]),
                    str(bucket.control[2]),
                    str(bucket.contradicted),
                    str(bucket.resuggested),
                    str(bucket.corrections),
                    _mean(bucket.corrections, bucket.n),
                    str(bucket.tokens_sum),
                    str(bucket.tokens_n),
                    _mean(bucket.tokens_sum, bucket.tokens_n),
                    str(bucket.reached),
                ]
            )
        )
    shown = [name for name, bucket in totals.items() if bucket.n >= MIN_PERCENT_ROWS]
    withheld = [f"{name} (n={totals[name].n})" for name in totals if totals[name].n < MIN_PERCENT_ROWS]
    lines.append("")
    if shown:
        lines.extend(
            [
                "## Rates",
                "",
                "followed / (followed + missed), ignoring n/a. Reached correct is reached / n.",
                "",
                _md_row(["condition", "n", "hidden", "discoverable", "control", "reached correct"]),
                _md_row(["---", "---", "---", "---", "---", "---"]),
            ]
        )
        for name in shown:
            bucket = totals[name]
            lines.append(
                _md_row(
                    [
                        name,
                        str(bucket.n),
                        _percent(bucket.hidden[0], bucket.hidden[1]),
                        _percent(bucket.discoverable[0], bucket.discoverable[1]),
                        _percent(bucket.control[0], bucket.control[1]),
                        _percent(bucket.reached, bucket.n - bucket.reached),
                    ]
                )
            )
        lines.append("")
    if withheld:
        lines.append("Percentages withheld for: " + ", ".join(withheld) + ".")
        lines.append("")
    item_lines = ["## Per item", ""]
    item_header = _md_row(["condition", "fixture", "item", "kind", "followed", "missed", "n/a"])
    any_items = False
    for name, bucket in totals.items():
        if bucket.n == 0:
            continue
        fixtures = sorted({fixture for fixture, _item in bucket.per_item})
        for fixture in fixtures:
            for item_id, item in keys[fixture].items():
                cell = bucket.per_item.get((fixture, item_id), [0, 0, 0])
                if not any_items:
                    item_lines.extend([item_header, _md_row(["---"] * 7)])
                    any_items = True
                item_lines.append(
                    _md_row([name, fixture, item_id, item.kind, str(cell[0]), str(cell[1]), str(cell[2])])
                )
    if any_items:
        lines.extend(item_lines)
        lines.append("")
    return "\n".join(lines)


def render_scores(csv_path: Path, keys_dir: Path | None = None) -> str:
    directory = keys_dir or Path(__file__).resolve().parent / "keys"
    keys = load_keys(directory)
    runs = load_runs(csv_path, keys)
    return format_report(summarize(runs, keys), keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate a filled bench results CSV.")
    parser.add_argument("csv_path", type=Path, help="Path to a filled results CSV.")
    args = parser.parse_args(argv)
    if not args.csv_path.is_file():
        print(f"error: no such file: {args.csv_path}", file=sys.stderr)
        print("Copy bench/results.template.csv and fill rows you actually ran. Do not invent rows.", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(render_scores(args.csv_path))
    except ScoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
