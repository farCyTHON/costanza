"""Cross-platform write lock for Costanza-owned files.

Choice: exclusive-create of ``.costanza/lock`` (``os.O_CREAT | os.O_EXCL``),
not ``fcntl``/``msvcrt`` flock. Those APIs differ by OS, and a Windows
mandatory lock plus a Unix flock would be two code paths. Exclusive create
is in the standard library, works the same on Windows, macOS and Linux, and
matches spec section 5.3. The JSONL/file rewrite itself uses ``os.replace``,
which is atomic on all three. We wait up to 5 seconds (50 ms poll). A lock
older than 30 seconds is stale; only ``doctor --fix`` removes it.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from costanza.exceptions import LockError
from costanza.paths import ProjectPaths

WAIT_SECONDS = 5.0
POLL_SECONDS = 0.05
STALE_SECONDS = 30.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _try_acquire(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags)
    except FileExistsError:
        return False
    try:
        os.write(fd, f"pid={os.getpid()}\nts={_iso_now()}\n".encode())
    finally:
        os.close(fd)
    return True


@contextmanager
def hold_lock(paths: ProjectPaths, timeout: float = WAIT_SECONDS) -> Iterator[None]:
    """Hold ``.costanza/lock`` for the duration of a write."""
    path = paths.lock
    deadline = time.monotonic() + timeout
    while True:
        if _try_acquire(path):
            try:
                yield
            finally:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            return
        if time.monotonic() >= deadline:
            raise LockError(
                "another costanza process is writing (.costanza/lock)",
                "if none is running, cz doctor --fix",
            )
        time.sleep(POLL_SECONDS)
