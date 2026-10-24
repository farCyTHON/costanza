"""Human gate for authoritative writes (spec section 3.5).

Every path that adds, removes or renumbers entries in COSTANZA.md MUST
call ``confirm``. Tests replace this function to simulate a person.
There is no flag, env var or config key that skips it.

I/O lives in a callback installed by the CLI (``install``) so this
module never touches standard streams.
"""

from __future__ import annotations

from collections.abc import Callable

from costanza.exceptions import UsageError

AskFn = Callable[[str], bool]

_ask: AskFn | None = None


def install(ask: AskFn | None) -> None:
    global _ask
    _ask = ask


def confirm(message: str, *, preconfirmed: bool = False) -> bool:
    """Ask ``accept …? [y/N]``. ``preconfirmed`` is the review ``a`` keypress."""
    if preconfirmed:
        return True
    if _ask is None:
        raise UsageError(
            "accept needs a person at an interactive terminal",
            "run cz review in your own terminal",
        )
    return _ask(message)
