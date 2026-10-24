from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


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
