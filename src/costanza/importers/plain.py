"""Plain text or Markdown. Best-effort: fences and labelled lines only."""

from __future__ import annotations

from pathlib import Path

from costanza.importers.scan import ScanResult, iter_text_file, scan_lines

HELP = (
    "Best-effort. Reads a text or Markdown file for fenced costanza blocks and "
    "lines that start with Decision, Rejected, Rule, Gotcha or Open question."
)


def read_plain(path: Path) -> ScanResult:
    """Stream ``path``. Prose that is not a label or a costanza fence is ignored."""
    return scan_lines(iter_text_file(path))
