"""Aider ``.aider.chat.history.md``. Best-effort, from the current writer.

Checked 2026-10-16 against Aider main:
https://github.com/Aider-AI/aider/blob/main/aider/io.py
https://github.com/Aider-AI/aider/blob/main/aider/utils.py

``user_input`` writes ``#### `` lines. ``ai_output`` writes plain Markdown.
``tool_output`` writes ``> `` lines. ``split_chat_history_markdown`` keeps
``#### `` as the user and other lines as the assistant, and drops ``> `` and
``# `` lines. Edit blocks use ``<<<<<<<`` ... ``>>>>>>>``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from costanza.importers.scan import ScanResult, iter_text_file, scan_lines

HELP = (
    "Best-effort. Reads .aider.chat.history.md human (####) and assistant lines. "
    "Skips > tool lines and <<<<<<< edit blocks."
)


def read_aider(path: Path) -> ScanResult:
    """Stream the history. Tool lines and diffs are not passed to the scanner."""
    truncated = False

    def kept() -> Iterator[tuple[int, str]]:
        nonlocal truncated
        in_diff = False
        for number, line in iter_text_file(path):
            if line.startswith("#### "):
                in_diff = False
                text = line[5:].strip()
                if text:
                    yield number, text
                continue
            if line.startswith("# ") or line.startswith("> "):
                in_diff = False
                continue
            stripped = line.strip()
            if stripped.startswith("<<<<<<<"):
                in_diff = True
                continue
            if in_diff:
                if stripped.startswith(">>>>>>>"):
                    in_diff = False
                continue
            if _unified_diff(stripped) or not stripped:
                continue
            yield number, stripped
        truncated = in_diff

    result = scan_lines(kept())
    if truncated:
        result.truncated = True
    return result


def _unified_diff(line: str) -> bool:
    return (
        line.startswith("diff --git ")
        or line.startswith("@@")
        or line.startswith("+++ ")
        or line.startswith("--- ")
    )
