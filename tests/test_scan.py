from __future__ import annotations

import shutil
from pathlib import Path

from costanza.constants import skeleton
from costanza.scan import detect
from tests.helpers import InvokeFn

FIXTURES = Path(__file__).parent / "fixtures" / "scan"


def _copy(name: str, dest: Path) -> None:
    shutil.copytree(FIXTURES / name, dest, dirs_exist_ok=True)


def test_detect_python() -> None:
    found = detect(FIXTURES / "python")
    assert found.stack is not None
    assert found.stack.startswith("python3.12")
    assert "FastAPI" in found.stack
    assert "pytest" in found.stack
    assert found.run == "shopbot"
    assert found.test == "pytest -q"
    assert found.layout is not None
    assert "src/" in found.layout
    assert "tests/" in found.layout


def test_detect_node() -> None:
    found = detect(FIXTURES / "node")
    assert found.stack is not None
    assert found.stack.startswith("node")
    assert "typescript" in found.stack
    assert "React" in found.stack
    assert found.run == "npm run dev"
    assert found.test == "npm test"
    assert found.layout is not None
    assert "src/" in found.layout


def test_detect_rust() -> None:
    found = detect(FIXTURES / "rust")
    assert found.stack == "rust"
    assert found.run == "cargo run"
    assert found.test == "cargo test"
    assert found.layout is not None
    assert "src/" in found.layout


def test_detect_mixed() -> None:
    found = detect(FIXTURES / "mixed")
    assert found.stack is not None
    assert "python3.11" in found.stack
    assert "Typer" in found.stack
    assert "node" in found.stack
    assert "React" in found.stack
    assert found.layout is not None
    assert "src/" in found.layout
    assert "web/" in found.layout


def test_scan_prints_diff_without_write(invoke: InvokeFn, tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text(skeleton("demo"), encoding="utf-8")
    _copy("python", tmp_path)
    result = invoke(["--root", str(tmp_path), "scan"])
    assert result.exit_code == 0, result.output
    assert "python3.12" in result.stdout
    assert "?" in result.stdout
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "stack: ?" in text


def test_scan_write_fills_empty_only(invoke: InvokeFn, tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text(skeleton("demo"), encoding="utf-8")
    _copy("python", tmp_path)
    written = invoke(["--root", str(tmp_path), "scan", "--write"])
    assert written.exit_code == 0, written.output
    text = (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    assert "python3.12" in text
    assert "shopbot" in text
    edited = text.replace("stack: python3.12, FastAPI, pytest", "stack: handmade")
    (tmp_path / "COSTANZA.md").write_text(edited, encoding="utf-8")
    again = invoke(["--root", str(tmp_path), "scan", "--write"])
    assert again.exit_code == 0
    assert "handmade" in (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")
    forced = invoke(["--root", str(tmp_path), "scan", "--write", "--force"])
    assert forced.exit_code == 0
    assert "python3.12" in (tmp_path / "COSTANZA.md").read_text(encoding="utf-8")


def test_scan_json(invoke: InvokeFn, tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text(skeleton("demo"), encoding="utf-8")
    _copy("rust", tmp_path)
    result = invoke(["--root", str(tmp_path), "scan", "--json"])
    assert result.exit_code == 0
    assert '"stack":"rust"' in result.stdout
    assert '"key":"stack"' in result.stdout
