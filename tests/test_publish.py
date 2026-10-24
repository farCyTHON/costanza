from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "costanza"

_COMMAND = re.compile(r"\bgit\s+(push|remote|commit)\b")
_GH = re.compile(r"(^|[\s\"'])gh(\s|$)")
_NETWORK_IMPORTS = frozenset(
    {
        "urllib",
        "requests",
        "httpx",
        "http.client",
        "socket",
        "ftplib",
        "smtplib",
    }
)
_NETWORK_CALLS = frozenset({"urlopen", "urlretrieve", "create_connection"})


def test_src_never_publishes_or_calls_the_network() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if alias.name in _NETWORK_IMPORTS or root in _NETWORK_IMPORTS:
                        offenders.append(f"{path.name}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if node.module in _NETWORK_IMPORTS or root in _NETWORK_IMPORTS:
                    offenders.append(f"{path.name}:{node.lineno} from {node.module}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _COMMAND.search(node.value):
                    offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
                if _GH.search(node.value):
                    offenders.append(f"{path.name}:{node.lineno} gh")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _NETWORK_CALLS:
                    offenders.append(f"{path.name}:{node.lineno} {node.func.attr}")
            elif isinstance(node, ast.List):
                values = [
                    item.value
                    for item in node.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                ]
                if "push" in values or "remote" in values:
                    offenders.append(f"{path.name}:{node.lineno} argv {values}")
                if "commit" in values and ("git" in values or values[:1] == ["commit"]):
                    offenders.append(f"{path.name}:{node.lineno} argv {values}")
    assert offenders == []
