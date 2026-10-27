"""Own sessions created for a worker, without taking ownership of borrowed I/O."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self

from tools.detail_worker_context import RuntimeContext, RuntimeContextFactory
from tools.safe_exception_diagnostics import safe_exception_text


class OwnedRuntimeContext:
    """Refresh fully before releasing the previous session; retain it on failure."""

    def __init__(self, factory: RuntimeContextFactory):
        self._factory = factory
        self._session: object | None = None

    def __enter__(self) -> Self:
        return self

    def __call__(self) -> RuntimeContext:
        context = self._factory()
        session, _pages = context
        previous, self._session = self._session, session
        if previous is not session:
            self._close(previous)
        return context

    def __exit__(self, *_exc_info: object) -> None:
        session, self._session = self._session, None
        self._close(session)

    @staticmethod
    def _close(session: object | None) -> None:
        close = getattr(session, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception as error:  # noqa: BLE001 - cleanup must preserve the batch outcome
            logging.getLogger(__name__).warning(
                "detail_worker_http_session_close_failed: %s",
                safe_exception_text(error),
            )
