"""Domain exceptions mapped to Costanza exit codes."""

from __future__ import annotations


class CostanzaError(Exception):
    """An error the CLI turns into a friendly panel and an exit code."""

    exit_code: int = 1

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(CostanzaError):
    """Bad flags, invalid input, or a command that has not landed yet."""

    exit_code = 2


class FindingsError(CostanzaError):
    """check / doctor / compact findings (exit 3). Unused in Step 2."""

    exit_code = 3


class NotFoundError(CostanzaError):
    """Missing COSTANZA.md, missing root, or similar."""

    exit_code = 1


class ExistsError(CostanzaError):
    """Refusing to overwrite without --force."""

    exit_code = 1


class ParseError(CostanzaError):
    """COSTANZA.md is unreadable as CF1 (E001)."""

    exit_code = 1


class ConfigError(CostanzaError):
    """config.toml has a wrong type or a value out of range."""

    exit_code = 1


class LockError(CostanzaError):
    """Another process holds .costanza/lock."""

    exit_code = 1


class GitError(CostanzaError):
    """git is missing, or the root is not a repository."""

    exit_code = 1


class ClipboardUnavailable(CostanzaError):
    """No clipboard backend exists on this machine."""

    exit_code = 1


class ClipboardError(CostanzaError):
    """A clipboard backend ran but could not copy the text exactly."""

    exit_code = 1
