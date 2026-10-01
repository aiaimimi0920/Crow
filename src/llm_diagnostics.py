"""Value-free diagnostics for configuration and provider failures.

Configured labels, URLs and provider messages can contain credentials. Log a
one-based pool position instead; leave the actual model keys and results intact.
"""

from __future__ import annotations


def model_slot(pool, model_name) -> int | str:
    for index, model in enumerate(pool, start=1):
        if model.get("name") == model_name:
            return index
    return "unknown"


def diagnostic_number(value) -> int | str:
    """Accept bounded plain integers, never stringify untrusted values."""
    if type(value) is int and 0 <= value <= 1_000_000_000:
        return value
    return "unknown"


def failure_kind(error) -> str:
    """Fixed categories retain troubleshooting value without exception text."""
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionError):
        return "connection"
    if isinstance(error, OSError):
        return "io"
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "invalid_data"
    if isinstance(error, ImportError):
        return "import"
    return "error"
