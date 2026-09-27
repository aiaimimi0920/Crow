"""Cookie completion ports shared by native orchestration and facade binding."""

from typing import Protocol


class CookieScheduler(Protocol):
    def __call__(
        self,
        payload: dict[str, object],
        completion_id: str | None,
        *,
        finalize_auth: bool = False,
        expected_challenge_id: str | None = None,
        completion_request: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


class CookieFinalizer(Protocol):
    def __call__(
        self,
        completion_id: str | None,
        *,
        expected_challenge_id: str | None = None,
        completion_request: dict[str, object] | None = None,
    ) -> dict[str, object]: ...
