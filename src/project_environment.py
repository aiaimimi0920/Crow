"""Dynamic Crow configuration aliases; reads never mutate process state."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, MutableMapping
from typing import TypeVar, overload

Reader = Callable[[str], str | None]
_T = TypeVar("_T")
_LOCK = threading.RLock()


class EnvironmentAliasConflict(ValueError):
    """Conflicting explicit configuration; the message contains keys only."""


def _keys(name: str) -> tuple[str, ...]:
    if name.startswith("FAPAI_"):
        name = "CROW_" + name[len("FAPAI_") :]
    if name.startswith("CROW_"):
        return name, "FAPAI_" + name[len("CROW_") :]
    return (name,)


@overload
def getenv(
    name: str, default: None = None, *, reader: Reader | None = None
) -> str | None: ...


@overload
def getenv(name: str, default: _T, *, reader: Reader | None = None) -> str | _T: ...


def getenv(
    name: str, default: _T | None = None, *, reader: Reader | None = None
) -> str | _T | None:
    """Read either spelling dynamically; explicit empty strings remain empty.

    An injected reader is the complete source of truth, with no global fallback.
    Distinct explicit alias values fail closed without including either value.
    Non-project names retain ordinary getenv behavior.
    """
    with _LOCK:
        read = os.getenv if reader is None else reader
        keys = _keys(name)
        values = [read(key) for key in keys]
        present = [value for value in values if value is not None]
        if len(present) > 1 and present[0] != present[1]:
            raise EnvironmentAliasConflict(
                "Conflicting environment aliases: " + ", ".join(keys)
            )
        return present[0] if present else default


def require_env(name: str, *, reader: Reader | None = None) -> str:
    """Required-subscript equivalent, preserving explicit empty strings."""
    value = getenv(name, reader=reader)
    if value is None:
        raise KeyError(_keys(name)[0])
    return value


def set_env(
    name: str, value: str, *, environ: MutableMapping[str, str] | None = None
) -> None:
    """Explicit writes update both aliases for cooperating helper consumers.

    Direct os.environ writes are outside this lock. Custom mapping writes are
    not generic transactions: a write error propagates and must stop the caller.
    """
    if not isinstance(value, str):
        raise TypeError("Environment values must be strings")
    with _LOCK:
        target = os.environ if environ is None else environ
        for key in _keys(name):
            target[key] = value


def setdefault_env(
    name: str, default: str, *, environ: MutableMapping[str, str] | None = None
) -> str:
    """Keep any existing value unchanged; initialize both names only if absent."""
    with _LOCK:
        target = os.environ if environ is None else environ
        current = getenv(name, reader=target.get)
        if current is not None:
            return current
        set_env(name, default, environ=target)
        return default
