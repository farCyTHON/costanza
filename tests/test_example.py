"""Paste examples are a shape. They must not look like a real project."""

from __future__ import annotations

import re
from pathlib import Path

from costanza.constants import (
    AGENT_BLOCK,
    EXAMPLE_LABEL,
    HANDOFF_PREAMBLE,
    PASTE_PROMPT,
    PASTE_WHEN,
    PROMPT_BOOTSTRAP,
)
from costanza.mcp_server import (
    _INSTRUCTIONS,
    NOW_DESCRIPTION,
    PACK_DESCRIPTION,
    PROPOSE_DESCRIPTION,
    READ_DESCRIPTION,
)

_README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
_SHOWN = {
    "preamble": HANDOFF_PREAMBLE,
    "prompt": PASTE_PROMPT,
    "bootstrap": PROMPT_BOOTSTRAP,
    "agents": AGENT_BLOCK,
    "readme": _README,
    "mcp-propose": PROPOSE_DESCRIPTION,
    "mcp-read": READ_DESCRIPTION,
    "mcp-now": NOW_DESCRIPTION,
    "mcp-pack": PACK_DESCRIPTION,
    "mcp-instructions": _INSTRUCTIONS,
}
_FENCE = re.compile(r"```costanza\n(.*?)```", re.DOTALL)
_ALLOWED = frozenset(
    {
        "decide",
        "reject",
        "rule",
        "gotcha",
        "ask",
        "now",
        "doing",
        "done",
        "next",
        "blocked",
        "one",
        "line",
        "reason",
        "path",
        "files",
    }
)
_REALISTIC = (
    "sqlite",
    "postgres",
    "webhook",
    "payment",
    "backoff",
    "shopbot",
    "telegram",
    "fastapi",
    "sqlalchemy",
    "cart",
)


def test_preamble_adds_a_block_only_for_a_real_entry() -> None:
    assert PASTE_WHEN in HANDOFF_PREAMBLE
    assert "Otherwise add nothing." in HANDOFF_PREAMBLE
    assert "copy a block" not in HANDOFF_PREAMBLE
    assert PASTE_WHEN in PASTE_PROMPT


def test_example_text_has_no_realistic_project_words() -> None:
    for name, text in _SHOWN.items():
        lowered = text.lower()
        for word in _REALISTIC:
            assert word not in lowered, f"{name} contains {word}"
        for body in _FENCE.findall(text):
            words = {item.lower() for item in re.findall(r"[A-Za-z]+", body)}
            extra = words - _ALLOWED
            assert not extra, f"{name} example has {sorted(extra)}"


def test_format_label_sits_above_every_example() -> None:
    for name, text in _SHOWN.items():
        start = 0
        while True:
            fence = text.find("```costanza", start)
            if fence < 0:
                break
            before = text[:fence].rstrip("\n")
            previous = before.splitlines()[-1] if before else ""
            assert previous == EXAMPLE_LABEL, f"{name} example has no format label"
            start = fence + len("```costanza")
