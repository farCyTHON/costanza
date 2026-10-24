from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from costanza.inbox import load_inbox
from tests.helpers import InvokeFn


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--name", "shopbot"])
    assert result.exit_code == 0, result.output


def test_concurrent_appends(tmp_path: Path) -> None:
    invoke = __import__("typer.testing", fromlist=["CliRunner"]).CliRunner()
    from costanza.cli import app

    result = invoke.invoke(app, ["--root", str(tmp_path), "init", "--name", "x"])
    assert result.exit_code == 0, result.output
    src = Path(__file__).resolve().parents[1] / "src"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from costanza.propose import propose\n"
        "propose('D', sys.argv[1], explicit=Path(sys.argv[2]))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(src)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, f"unique decision {n} -- because {n}", str(tmp_path)],
            env=env,
            cwd=str(tmp_path),
        )
        for n in (1, 2)
    ]
    codes = [proc.wait(timeout=20) for proc in procs]
    assert codes == [0, 0]
    inbox = load_inbox(tmp_path / ".costanza" / "inbox.jsonl")
    ids = sorted(item.id for item in inbox.proposals())
    assert ids == ["p1", "p2"]
    texts = {item.text for item in inbox.proposals()}
    assert texts == {"unique decision 1", "unique decision 2"}
