"""Background cadence for the existing manual solver retry policy."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import ClassVar, Protocol

logger = logging.getLogger(__name__)


class RetryLoopClock(Protocol):
    def sleep(self, seconds: float) -> None: ...


class RetryLoopHost(Protocol):
    time: RetryLoopClock
    _trigger_manual_solver_retry_if_due: Callable[[], dict[str, object]]
    _manual_solver_retry_poll_seconds: Callable[[], float]


@dataclass(frozen=True)
class SolverRetryLoop:
    host: RetryLoopHost

    __all__: ClassVar[list[str]] = ["manual_solver_retry_thread"]

    def manual_solver_retry_thread(self, stop_event: Event | None = None) -> None:
        host = self.host
        while stop_event is None or not stop_event.is_set():
            try:
                result = host._trigger_manual_solver_retry_if_due()
                if result.get("queued"):
                    request = result.get("solver_request")
                    solver_request = request if isinstance(request, dict) else {}
                    logger.info(
                        "Manual-required solver retry queued attempt=%s target=%s",
                        result.get("attempt"),
                        solver_request.get("target_url"),
                    )
            except Exception:
                logger.exception("Manual-required solver retry monitor failed")
            interval = host._manual_solver_retry_poll_seconds()
            if stop_event is None:
                host.time.sleep(interval)
            elif stop_event.wait(interval):
                return
