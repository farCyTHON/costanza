"""Write the NOW block directly (no inbox)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from costanza.config import load_config
from costanza.constants import NOW_ITEM_MAX, NOW_LIST_MAX
from costanza.exceptions import UsageError
from costanza.format import SOFT_LINE_LIMIT, Now
from costanza.paths import ProjectPaths, discover_root
from costanza.scrub import redact
from costanza.store import WriteResult, mutate_file, read_file, replace_now
from costanza.text import clip_words, require_clean


@dataclass
class NowResult:
    now: Now
    changed: tuple[str, ...]
    redacted: tuple[str, ...]
    write: WriteResult | None
    merged: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, str]:
        return {
            "doing": self.now.doing,
            "done": self.now.done,
            "next": self.now.next,
            "blocked": self.now.blocked,
        }


def _fit_value(value: str, label: str, warnings: list[str]) -> str:
    if len(value) <= SOFT_LINE_LIMIT:
        return value
    clipped = clip_words(value, SOFT_LINE_LIMIT)
    warnings.append(
        f"{label} truncated to {len(clipped)} characters (was {len(value)}; limit {SOFT_LINE_LIMIT})"
    )
    return clipped


def _compact_list(value: str, key: str) -> str:
    """Keep the 3 newest items, each at most 60 characters. Newest is first."""
    if value in {"", "none"}:
        return value
    items = [item.strip() for item in value.split(",") if item.strip()]
    kept: list[str] = []
    for item in items[:NOW_LIST_MAX]:
        kept.append(clip_words(item, NOW_ITEM_MAX) if len(item) > NOW_ITEM_MAX else item)
    assembled = ", ".join(kept)
    room = SOFT_LINE_LIMIT - len(f"{key}: ")
    if len(assembled) > room:
        assembled = clip_words(assembled, room)
    return assembled or "none"


def apply_now(
    *,
    doing: str | None = None,
    done: str | None = None,
    next_items: str | None = None,
    blocked: str | None = None,
    add_done: str | None = None,
    cwd: Path | None = None,
    explicit: Path | None = None,
) -> NowResult:
    if done is not None and add_done is not None:
        raise UsageError("--add-done cannot be combined with --done", "use one of them")
    root = discover_root(cwd, explicit, allow_cwd=False)
    paths = ProjectPaths(root)
    config = load_config(paths.config)
    previous, document = read_file(paths)
    now = Now(
        doing=document.now.doing,
        done=document.now.done,
        next=document.now.next,
        blocked=document.now.blocked,
        line=document.now.line,
    )
    changed: list[str] = []
    names: list[str] = []
    warnings: list[str] = []

    def _set(key: str, value: str | None) -> None:
        if value is None:
            return
        cleaned = "none" if value.strip().lower() == "none" else require_clean(value, key)
        red = redact(cleaned, list(config.secret_allow))
        names.extend(red.names)
        text = red.text
        if text != "none":
            text = _fit_value(text, key, warnings)
            if key in {"done", "next"}:
                text = _compact_list(text, key)
            else:
                room = SOFT_LINE_LIMIT - len(f"{key}: ")
                if len(text) > room:
                    text = clip_words(text, room)
        setattr(now, key, text)
        changed.append(key)

    _set("doing", doing)
    _set("done", done)
    _set("next", next_items)
    _set("blocked", blocked)
    if add_done is not None:
        cleaned = require_clean(add_done, "add-done")
        red = redact(cleaned, list(config.secret_allow))
        names.extend(red.names)
        item = _fit_value(red.text, "add-done", warnings)
        item = clip_words(item, NOW_ITEM_MAX)
        if now.done in {"", "none"}:
            now.done = item
        else:
            now.done = f"{item}, {now.done}"
        now.done = _compact_list(now.done, "done")
        changed.append("done")

    if not changed:
        return NowResult(now=now, changed=(), redacted=(), write=None)

    result = mutate_file(paths, previous, lambda doc: replace_now(doc, now), "NOW " + ", ".join(changed))
    return NowResult(
        now=now,
        changed=tuple(changed),
        redacted=tuple(dict.fromkeys(names)),
        write=result,
        merged=result.merged,
        warnings=tuple(warnings),
    )
