"""Thread-local HTTP slots shared by one explicit detail snapshot retry job."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event


@dataclass
class DetailProbeBudget:
    limit: int
    stop_event: Event | None = None
    used: int = 0

    @property
    def available(self) -> bool:
        return self.used < self.limit and not (
            self.stop_event is not None and self.stop_event.is_set()
        )

    def consume(self) -> None:
        if not self.available:
            raise RuntimeError("Detail snapshot HTTP budget unavailable")
        self.used += 1


_CURRENT: ContextVar[DetailProbeBudget | None] = ContextVar(
    "detail_snapshot_http_budget", default=None
)


def current_detail_probe_budget() -> DetailProbeBudget | None:
    return _CURRENT.get()


@contextmanager
def snapshot_probe_budget(
    scope: object, limit: int, stop_event: Event | None
) -> Iterator[DetailProbeBudget | None]:
    budget = (
        DetailProbeBudget(limit, stop_event)
        if str(scope or "").strip().lower() == "detail"
        else None
    )
    token = _CURRENT.set(budget)
    try:
        yield budget
    finally:
        _CURRENT.reset(token)
