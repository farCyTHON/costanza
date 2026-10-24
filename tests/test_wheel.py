"""A wheel built with no downloads runs init and status in a fresh venv."""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path


def _build_wheel(root: Path, dest: Path) -> Path:
    """Pack the package with the stdlib. No build backend and no download."""
    dist_info = "costanza-0.1.0.dist-info"
    files: dict[str, bytes] = {}
    package = root / "src" / "costanza"
    for src in package.rglob("*.py"):
        if "__pycache__" in src.parts:
            continue
        arc = "costanza/" + src.relative_to(package).as_posix()
        files[arc] = src.read_bytes()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: costanza\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files[f"{dist_info}/METADATA"] = (
        b"Metadata-Version: 2.1\nName: costanza\nVersion: 0.1.0\n"
        b"Summary: A local, token-thrifty handoff file for any AI coding session.\n"
        b"Requires-Python: >=3.10,<3.14\n"
    )
    files[f"{dist_info}/entry_points.txt"] = (
        b"[console_scripts]\ncostanza = costanza.cli:main\ncz = costanza.cli:main\n"
    )
    rows: list[str] = []
    for arc, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        rows.append(f"{arc},sha256={digest},{len(data)}")
    rows.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(rows) + "\n").encode()
    path = dest / "costanza-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for arc, data in files.items():
            archive.writestr(arc, data)
    return path


def test_wheel_runs_init_and_status_offline(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = _build_wheel(root, dist)
    venv = tmp_path / "venv"
    made = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert made.returncode == 0, made.stderr
    if sys.platform == "win32":
        py = venv / "Scripts" / "python.exe"
        site = venv / "Lib" / "site-packages"
    else:
        py = venv / "bin" / "python"
        site = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    parent = Path(sysconfig.get_path("purelib"))
    (site / "dev-deps.pth").write_text(str(parent) + "\n", encoding="utf-8")
    installed = subprocess.run(
        [str(py), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PIP_NO_INDEX": "1"},
    )
    assert installed.returncode == 0, installed.stderr
    project = tmp_path / "proj"
    project.mkdir()
    init = subprocess.run(
        [str(py), "-m", "costanza", "--root", str(project), "init", "--agents", "none"],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert init.returncode == 0, init.stderr + init.stdout
    status = subprocess.run(
        [str(py), "-m", "costanza", "--root", str(project), "status"],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert status.returncode == 0, status.stderr + status.stdout
