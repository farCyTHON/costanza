from __future__ import annotations

from pathlib import Path

from tests.helpers import InvokeFn, InvokeResult


def test_domain_error_panel_no_traceback(invoke: InvokeFn, tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x", encoding="utf-8")
    result: InvokeResult = invoke(["--root", str(tmp_path), "init"])
    assert result.exit_code == 1
    assert "error" in result.stderr
    assert "next:" in result.stderr
    assert "Traceback" not in result.stderr


def test_debug_shows_traceback(invoke: InvokeFn, tmp_path: Path) -> None:
    (tmp_path / "COSTANZA.md").write_text("x", encoding="utf-8")
    result: InvokeResult = invoke(
        ["--root", str(tmp_path), "init"],
        env={"COSTANZA_DEBUG": "1"},
    )
    assert result.exit_code == 1
    assert "Traceback" in result.stderr
    assert "ExistsError" in result.stderr
