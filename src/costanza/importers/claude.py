"""Claude Code sessions. Best-effort, and currently a refusal.

Checked 2026-10-16 against https://code.claude.com/docs/en/sessions.
Transcripts are JSONL at ``~/.claude/projects/<encoded-path>/<id>.jsonl``.
The same page says each line is a message, tool use, or metadata entry, and
that the entry format is internal and changes between versions. No entry
schema is published there, so this adapter does not guess one.
"""

from __future__ import annotations

from pathlib import Path

from costanza.exceptions import UsageError

HELP = (
    "Best-effort. Claude Code's JSONL entry format is unpublished, so this "
    "adapter does not parse it."
)

_PAGE = "https://code.claude.com/docs/en/sessions"


def read_claude(path: Path) -> None:
    """Refuse to parse ``path``. The file is not opened."""
    _ = path
    raise UsageError(
        "claude-code transcript entries are unpublished. "
        f"Files are JSONL under ~/.claude/projects/, and {_PAGE} "
        "(checked 2026-10-16) says the entry format is internal and changes "
        "between versions. This best-effort adapter does not guess it.",
        "export the chat to a text file and run cz import plain FILE",
    )
