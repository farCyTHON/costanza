"""Secret detection and redaction. Never stores the original match."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Spec section 10.1, then extras the Step 4 prompt asked for (bearer, nearby entropy).
_DETECTORS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "all"),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "all"),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "all"),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), "all"),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), "all"),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "all"),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b"), "all"),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "all"),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "all"),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"), "all"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "all"),
    (
        "url_credentials",
        re.compile(r"\b([a-z][a-z0-9+.-]*://[^\s/:@]+):([^\s/@]+)@"),
        "password",
    ),
    (
        "assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"
            r"\s*[:=]\s*[\"']?([^\s\"']{8,})"
        ),
        "value",
    ),
    ("bearer", re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{20,})"), "value"),
    (
        "entropy",
        re.compile(
            r"(?i)\b(?:key|token|secret|password)\b[:\s=]+([A-Za-z0-9/+_=.-]{24,})"
        ),
        "value",
    ),
)


@dataclass(frozen=True)
class Redaction:
    text: str
    names: tuple[str, ...]


def _shannon(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _high_entropy(value: str) -> bool:
    """True only for mixed-class blobs. Git SHAs and prose stay out."""
    if len(value) < 24:
        return False
    classes = sum(
        (
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(c in "/+_=" for c in value),
        )
    )
    return classes >= 3 and len(set(value)) >= 12 and _shannon(value) >= 3.3


def _allowed(match: str, allow: frozenset[str]) -> bool:
    return match in allow


def redact(text: str, allow: list[str] | None = None) -> Redaction:
    """Replace every hit with ``[REDACTED:<name>]``. Original is dropped."""
    allowed = frozenset(allow or [])
    names: list[str] = []
    out = text
    for name, pattern, mode in _DETECTORS:
        if name == "openai_key" and "anthropic_key" in names:
            # anthropic keys also match the openai pattern; keep the first name.
            continue

        def repl(match: re.Match[str], det: str = name, how: str = mode) -> str:
            raw = match.group(0)
            captured = match.group(1) if match.lastindex else raw
            secret = match.group(2) if how == "password" and match.lastindex and match.lastindex >= 2 else captured
            if _allowed(raw, allowed) or _allowed(secret, allowed):
                return raw
            if det == "entropy" and not _high_entropy(secret):
                return raw
            names.append(det)
            token = f"[REDACTED:{det}]"
            if how == "password":
                return f"{match.group(1)}:{token}@"
            if how == "value":
                return raw[: match.start(1) - match.start(0)] + token + raw[match.end(1) - match.start(0) :]
            return token

        out = pattern.sub(repl, out)
    return Redaction(text=out, names=tuple(names))


def find_names(text: str, allow: list[str] | None = None) -> tuple[str, ...]:
    return redact(text, allow).names


@dataclass(frozen=True)
class SecretHit:
    name: str
    line: int
    masked: str


def mask_secret(value: str) -> str:
    shown = value[:4] if value else ""
    return f"{shown}…"


def find_hits(text: str, allow: list[str] | None = None) -> list[SecretHit]:
    """Scan each line. The full secret is never kept past this function."""
    allowed = frozenset(allow or [])
    hits: list[SecretHit] = []
    for number, line in enumerate(text.splitlines(), start=1):
        seen_spans: list[tuple[int, int]] = []
        names_here: list[str] = []
        for name, pattern, mode in _DETECTORS:
            if name == "openai_key" and "anthropic_key" in names_here:
                continue
            for match in pattern.finditer(line):
                raw = match.group(0)
                captured = match.group(1) if match.lastindex else raw
                secret = (
                    match.group(2)
                    if mode == "password" and match.lastindex and match.lastindex >= 2
                    else captured
                )
                if _allowed(raw, allowed) or _allowed(secret, allowed):
                    continue
                if name == "entropy" and not _high_entropy(secret):
                    continue
                span = (match.start(), match.end())
                if any(span[0] < end and start < span[1] for start, end in seen_spans):
                    continue
                seen_spans.append(span)
                names_here.append(name)
                hits.append(SecretHit(name=name, line=number, masked=mask_secret(secret)))
    return hits
