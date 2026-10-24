"""Build a handoff pack and the short prompt bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from costanza.config import load_config
from costanza.constants import HANDOFF_PREAMBLE, PASTE_PROMPT, PROMPT_BOOTSTRAP
from costanza.format import compile_to_budget
from costanza.inbox import load_inbox
from costanza.paths import ProjectPaths, discover_root
from costanza.store import read_file
from costanza.tokens import active_count, bind


@dataclass
class HandoffResult:
    text: str
    tokens: int
    file_tokens: int
    instruction_tokens: int
    cut: tuple[str, ...]
    copied: str | None = None


def prompt_text() -> str:
    """One-sentence bootstrap for tools that can read COSTANZA.md."""
    return PROMPT_BOOTSTRAP if PROMPT_BOOTSTRAP.endswith("\n") else PROMPT_BOOTSTRAP + "\n"


def paste_instructions() -> str:
    text = PASTE_PROMPT
    return text if text.endswith("\n") else text + "\n"


def build_handoff(
    *,
    budget: int | None = None,
    for_chat: bool = False,
    with_inbox: bool = False,
    no_prompt: bool = False,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> HandoffResult:
    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    bind(config.tokenizer, config.tokenizer_encoding, config.tokenizer_cache, root)
    ceiling = budget if budget is not None else config.budget_tokens
    _previous, document = read_file(paths)
    packed = compile_to_budget(document, ceiling)
    pack = packed.text if packed.text.endswith("\n") else packed.text + "\n"

    parts: list[str] = []
    if for_chat:
        parts.append(HANDOFF_PREAMBLE.rstrip() + "\n")
        parts.append("\n")
    parts.append(pack if pack.endswith("\n") else pack + "\n")

    if with_inbox:
        inbox = load_inbox(paths.inbox)
        pending = [item for item in inbox.proposed()]
        parts.append("\n")
        parts.append("PENDING (proposed, not ratified):\n")
        if pending:
            for item in pending:
                line = f"{item.id} {item.kind} {item.text}"
                if item.why:
                    line += f" -- {item.why}"
                parts.append(line + "\n")
        else:
            parts.append("(none)\n")

    instructions = ""
    if for_chat and not no_prompt:
        instructions = paste_instructions()
        parts.append("\n")
        parts.append("---\n")
        parts.append("\n")
        parts.append(instructions)

    text = "".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    file_tokens = packed.tokens
    instruction_tokens = active_count(instructions) if instructions else 0
    if for_chat:
        instruction_tokens = active_count(HANDOFF_PREAMBLE + "\n\n" + (instructions or ""))
    return HandoffResult(
        text=text,
        tokens=active_count(text),
        file_tokens=file_tokens,
        instruction_tokens=instruction_tokens,
        cut=packed.cut,
    )
