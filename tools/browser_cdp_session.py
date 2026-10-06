"""Scoped ownership of temporary page CDP sessions, never the host browser."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


def detach_cdp_session(session: Any) -> None:
    """Best-effort detach must not replace the operation's primary result."""
    detach = getattr(session, "detach", None)
    if callable(detach):
        try:
            detach()
        except Exception as error:  # noqa: BLE001 -- a reclaimed session must not mask the operation
            logger.debug(
                "Temporary CDP session detach unavailable (%s)", type(error).__name__
            )


@contextmanager
def held_cdp_session(context: Any, page: Any) -> Iterator[Any]:
    """Retain page-scoped configuration until navigation and document reads finish."""
    session = context.new_cdp_session(page)
    try:
        yield session
    finally:
        detach_cdp_session(session)
