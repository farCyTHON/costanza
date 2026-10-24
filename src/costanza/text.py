"""Normalisation, hashes and path checks for proposal input."""

from __future__ import annotations

import hashlib
import unicodedata

from costanza.exceptions import UsageError
from costanza.format import HARD_LINE_LIMIT, MAX_FILES, forbidden_label, path_problem


def normalise(value: str) -> str:
    """TAB to space, trim, collapse whitespace, NFC (spec 1.8)."""
    value = value.replace("\t", " ")
    value = " ".join(value.split())
    return unicodedata.normalize("NFC", value)


def hash_norm(value: str) -> str:
    """Dedupe normalisation (spec 3.3)."""
    value = unicodedata.normalize("NFKC", value)
    value = value.casefold()
    value = " ".join(value.split())
    return value.rstrip(".")


def content_hash(kind: str, text: str) -> str:
    payload = f"{kind}\n{hash_norm(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def clip_words(text: str, width: int) -> str:
    """Cut ``text`` to ``width`` on a word boundary. No ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    space = text.rfind(" ", 0, width + 1)
    if space <= 0:
        return text[:width].rstrip()
    return text[:space].rstrip()


def require_clean(value: str, label: str) -> str:
    cleaned = normalise(value)
    if not cleaned:
        raise UsageError(f"{label} is empty", "pass non-empty text")
    if len(cleaned) > HARD_LINE_LIMIT:
        raise UsageError(
            f"{label} is {len(cleaned)} characters; max is {HARD_LINE_LIMIT}",
            "shorten the text",
        )
    bad = forbidden_label(cleaned)
    if bad is not None:
        raise UsageError(
            f"{label} contains forbidden character {bad}",
            "remove it and try again",
        )
    if cleaned.startswith("#"):
        raise UsageError(f"{label} must not start with #", "rewrite the text")
    return cleaned


def parse_files(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return []
    parts = [normalise(item) for item in raw.split(",")]
    parts = [item for item in parts if item]
    if len(parts) > MAX_FILES:
        raise UsageError(
            f"{len(parts)} file paths; keep at most {MAX_FILES}",
            "drop some --files values",
        )
    for path in parts:
        problem = path_problem(path)
        if problem is not None:
            raise UsageError(f"unsafe file path {path!r}: {problem}", "use a repo-relative path")
    return parts


def split_inline(text: str, why: str | None) -> tuple[str, str | None]:
    if " -- " in text:
        if why is not None:
            raise UsageError(
                "inline ' -- ' together with --why",
                "use one or the other",
            )
        left, right = text.split(" -- ", 1)
        return left, right
    return text, why
