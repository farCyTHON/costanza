"""Token counts for COSTANZA.md.

Default estimator (no dependencies)
-----------------------------------
For each line L, excluding its newline, let c be the number of Unicode
code points and w be ``len(L.split())`` (whitespace-separated words):

    line_tokens(L) = max(ceil(c / 4), ceil(4 * w / 3)) + 1

implemented with integer arithmetic:

    max((c + 3) // 4, (4 * w + 2) // 3) + 1

The file total is the sum over every line as written. A trailing newline
does not add an extra blank line; an inner blank line costs 1 token.

This is a deterministic heuristic, not a BPE tokenizer. On English-heavy
CF1 files it tends to overestimate cl100k_base / o200k_base by about
5–20%. It can underestimate CJK (BPE is often near 1 token per character
while this formula is closer to 1 per 4) and can drift on punctuation-
only lines. Costanza always labels the result as an estimate. The locked
fixtures are 238 tokens (tiny) and 1,666 tokens (near-budget).

Optional exact counter
----------------------
``count_exact`` uses tiktoken when the ``tokens`` extra is installed
(``pip install costanza[tokens]``) and the encoding file is already in
``tokenizer_cache``. The cache file name is the SHA-1 of the encoding
URL, which is how tiktoken names that file. The directory is passed as
``TIKTOKEN_CACHE_DIR`` for that one call and then restored. If the
extra, the directory or the file is missing, the function returns None
and never tries the network.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
from collections.abc import Callable
from pathlib import Path
from typing import Final

ESTIMATOR_NAME: Final = "estimate"
EXACT_NAME: Final = "tiktoken"
DEFAULT_ENCODING: Final = "o200k_base"
FALLBACK_WARNING: Final = "tokenizer unavailable offline; using estimate (see cz doctor)"

# Verified 2026-10-16 against tiktoken/load.py and tiktoken_ext/openai_public.py
# on openai/tiktoken main. The cache file name is SHA-1 of this URL.
_ENCODING_URLS: Final[dict[str, str]] = {
    "o200k_base": "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
    "o200k_harmony": "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
    "cl100k_base": "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
    "p50k_base": "https://openaipublic.blob.core.windows.net/encodings/p50k_base.tiktoken",
    "p50k_edit": "https://openaipublic.blob.core.windows.net/encodings/p50k_base.tiktoken",
    "r50k_base": "https://openaipublic.blob.core.windows.net/encodings/r50k_base.tiktoken",
}

_tokenizer: str = ESTIMATOR_NAME
_encoding: str = DEFAULT_ENCODING
_cache: Path | None = None
_warned: bool = False
_emit: Callable[[str], None] | None = None


def line_tokens(line: str) -> int:
    """Tokens for one line, excluding its newline."""
    chars = len(line)
    words = len(line.split())
    return max((chars + 3) // 4, (4 * words + 2) // 3) + 1


def file_tokens(text: str) -> int:
    """Sum ``line_tokens`` over every line of ``text`` as written."""
    if text.endswith("\n"):
        text = text[:-1]
    if text.endswith("\r"):
        text = text[:-1]
    if not text:
        return 0
    return sum(line_tokens(line) for line in text.splitlines())


def estimate(text: str) -> int:
    """Dependency-free token estimate for a whole file."""
    return file_tokens(text)


def budget_state(tokens: int, budget: int, warn_at: float) -> str:
    """Return ``ok``, ``warn`` or ``over`` (spec section 2.3)."""
    threshold = int(budget * warn_at)
    if tokens > budget:
        return "over"
    if tokens >= threshold:
        return "warn"
    return "ok"


def exact_available() -> bool:
    """True when the ``tokens`` extra (tiktoken) can be imported."""
    return importlib.util.find_spec("tiktoken") is not None


def cache_name(encoding: str) -> str | None:
    """SHA-1 cache file name for a verified encoding URL, or None."""
    url = _ENCODING_URLS.get(encoding)
    if url is None:
        return None
    return hashlib.sha1(url.encode()).hexdigest()


def begin_command() -> None:
    """Start a command on the estimator. Clears a leftover tokenizer mode."""
    global _tokenizer, _encoding, _cache, _warned, _emit
    _tokenizer = ESTIMATOR_NAME
    _encoding = DEFAULT_ENCODING
    _cache = None
    _warned = False
    _emit = None


def set_warn(emit: Callable[[str], None] | None) -> None:
    """Install the one-line warning printer. The CLI sets this; core does not print."""
    global _emit
    _emit = emit


def bind(tokenizer: str, encoding: str, cache: str, root: Path) -> None:
    """Select the counter for this command from config. Does not touch the network."""
    global _tokenizer, _encoding, _cache
    _tokenizer = tokenizer if tokenizer in {ESTIMATOR_NAME, EXACT_NAME} else ESTIMATOR_NAME
    _encoding = encoding or DEFAULT_ENCODING
    if not cache:
        _cache = None
        return
    path = Path(cache)
    if not path.is_absolute():
        path = root / path
    _cache = path


def take_warning() -> str | None:
    """Return the fallback warning once, when nothing has printed it yet."""
    global _warned
    if not _warned or _emit is not None:
        return None
    _warned = False
    return FALLBACK_WARNING


def measure(text: str) -> tuple[int, str]:
    """Count ``text``. Falls back to the estimator and warns once per command."""
    if _tokenizer == EXACT_NAME:
        exact = count_exact(text, _encoding, _cache)
        if exact is not None:
            return exact, EXACT_NAME
        _note_fallback()
    return estimate(text), ESTIMATOR_NAME


def active_count(text: str) -> int:
    """The active counter, estimator unless ``bind`` selected a usable cache."""
    return measure(text)[0]


def count_exact(
    text: str,
    encoding: str = DEFAULT_ENCODING,
    cache: Path | None = None,
) -> int | None:
    """Return a tiktoken count, or None if the extra or the cache file is missing.

    Never downloads encoding files. The cache file must already exist.
    ``TIKTOKEN_CACHE_DIR`` is pointed at that directory for this call only.
    """
    if cache is None or not cache.is_dir():
        return None
    name = cache_name(encoding)
    if name is None or not (cache / name).is_file():
        return None
    previous = os.environ.get("TIKTOKEN_CACHE_DIR")
    os.environ["TIKTOKEN_CACHE_DIR"] = str(cache)
    try:
        try:
            tiktoken = importlib.import_module("tiktoken")
        except ImportError:
            return None
        try:
            encoder = tiktoken.get_encoding(encoding)
            return len(encoder.encode(text))
        except Exception:
            return None
    finally:
        if previous is None:
            os.environ.pop("TIKTOKEN_CACHE_DIR", None)
        else:
            os.environ["TIKTOKEN_CACHE_DIR"] = previous


def count(text: str, *, exact: bool = False) -> tuple[int, str]:
    """Return ``(n, method)``. ``method`` is ``tiktoken`` or ``estimate``."""
    if exact:
        value = count_exact(text, _encoding, _cache)
        if value is not None:
            return value, EXACT_NAME
        _note_fallback()
    return estimate(text), ESTIMATOR_NAME


def _note_fallback() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    if _emit is not None:
        _emit(FALLBACK_WARNING)
