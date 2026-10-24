from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "costanza"
ROOT = Path(__file__).resolve().parents[1]

CORE_MODULES = [
    "costanza",
    "costanza.constants",
    "costanza.exceptions",
    "costanza.io",
    "costanza.estimate",
    "costanza.tokens",
    "costanza.paths",
    "costanza.config",
    "costanza.cf1",
    "costanza.format",
    "costanza.check",
    "costanza.lock",
    "costanza.gate",
    "costanza.scrub",
    "costanza.text",
    "costanza.store",
    "costanza.inbox",
    "costanza.propose",
    "costanza.now",
    "costanza.accept",
    "costanza.init",
    "costanza.status",
    "costanza.git",
    "costanza.scan",
    "costanza.compact",
    "costanza.sync",
    "costanza.clipboard",
    "costanza.agents",
    "costanza.paste",
    "costanza.handoff",
    "costanza.hooks",
    "costanza.mcp_server",
    "costanza.importers",
    "costanza.importers.scan",
    "costanza.importers.plain",
    "costanza.importers.aider",
    "costanza.importers.claude",
    "costanza.doctor",
]


def test_core_does_not_import_rich_or_typer() -> None:
    script = (
        "import sys\n"
        + "".join(f"import {name}\n" for name in CORE_MODULES)
        + "mods = set(sys.modules)\n"
        + "bad = sorted(m for m in mods if m == 'rich' or m.startswith('rich.') "
        "or m == 'typer' or m.startswith('typer.'))\n"
        + "raise SystemExit(0 if not bad else 'imported: ' + ','.join(bad))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_only_ui_prints() -> None:
    offenders: list[str] = []
    for path in SRC.glob("*.py"):
        if path.name == "ui.py":
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                offenders.append(f"{path.name}:print")
        if "sys.stdout" in text or "sys.stderr" in text:
            offenders.append(f"{path.name}:stdio")
        if "Console(" in text:
            offenders.append(f"{path.name}:Console")
    assert offenders == [], offenders


def test_no_click_or_private_typer() -> None:
    for path in SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import click" not in text
        assert "from click" not in text
        assert "typer._click" not in text


def test_mypy_config_is_strict() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.mypy]" in text
    assert "strict = true" in text
    assert 'python_version = "3.10"' in text
    assert 'files = ["src", "tests"]' in text
    assert "warn_unreachable = true" in text
    assert "disallow_untyped_defs = false" not in text
    assert "ignore_errors" not in text
