from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Drop ANSI escape sequences so assertions see the visible text."""
    return _ANSI.sub("", text)


class InvokeResult(Protocol):
    @property
    def exit_code(self) -> int: ...

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...

    @property
    def output(self) -> str: ...


InvokeFn = Callable[..., InvokeResult]
