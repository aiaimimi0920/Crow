"""Native cookie refresh orchestration and runtime state access."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast

from .auth_cookie_paths import EnvironmentReader
from .auth_cookie_snapshot_state import AuthCookieSnapshotState
from .runtime_state import RuntimeState
from .solver_captcha_reports import PayloadFlag


class CookieHealthProbe(Protocol):
    def __call__(
        self,
        cookies: list[dict[str, object]],
        sample_urls: list[str],
        *,
        cdp_endpoint: str = "",
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class AuthCookieSnapshot:
    runtime: Callable[[], RuntimeState]
    env: EnvironmentReader
    flag: PayloadFlag
    resolve_path: Callable[[dict[str, object]], str]
    normalize_endpoint: Callable[[object], str]
    permitted: Callable[[str], bool]
    export: Callable[[str], list[dict[str, object]]]
    summarize: Callable[[list[dict[str, object]]], Mapping[str, object]]
    sample_urls: Callable[[dict[str, object]], list[str]]
    health: CookieHealthProbe
    write: Callable[[list[dict[str, object]], str], None]
    state: Callable[[], AuthCookieSnapshotState]

    __all__: ClassVar[list[str]] = [
        "_export_auth_cdp_cookies",
        "_summarize_auth_cookies",
        "_write_auth_cookie_snapshot",
        "_probe_auth_cookie_snapshot_health",
        "_refresh_auth_cookie_snapshot",
        "_auth_cookie_snapshot_retry_attempts",
        "_auth_cookie_snapshot_retry_backoff_seconds",
        "_auth_cookie_snapshot_runtime_status",
        "_set_auth_cookie_snapshot_state",
        "_auth_cookie_snapshot_runtime_state",
    ]

    def _export_auth_cdp_cookies(self, cdp_endpoint: str) -> list[dict[str, object]]:
        from src.cdp_cookie_transport import export_cdp_cookies

        return export_cdp_cookies(cdp_endpoint)

    def _summarize_auth_cookies(
        self, cookies: list[dict[str, object]]
    ) -> dict[str, object]:
        from src.cookie_snapshot_metadata import summarize_cookie_snapshot

        return cast("dict[str, object]", summarize_cookie_snapshot(cookies))

    def _write_auth_cookie_snapshot(
        self, cookies: list[dict[str, object]], snapshot_path: str
    ) -> None:
        from src.cookie_snapshot_storage import write_cookie_snapshot

        write_cookie_snapshot(cookies, snapshot_path)

    def _probe_auth_cookie_snapshot_health(
        self,
        cookies: list[dict[str, object]],
        sample_urls: list[str],
        *,
        cdp_endpoint: str = "",
    ) -> dict[str, object]:
        from src.auth_cookie_health import probe_cookie_snapshot_health

        return probe_cookie_snapshot_health(
            cookies, sample_urls, cdp_endpoint=cdp_endpoint
        )

    def _refresh_auth_cookie_snapshot(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        if not self.flag(payload, "refresh_cookie_snapshot", True):
            return {"refreshed": False, "reason": "disabled_by_request"}

        snapshot_path = self.resolve_path(payload)
        if not snapshot_path:
            return {"refreshed": False, "reason": "cookie_snapshot_path_not_configured"}

        request_cdp_endpoint = payload.get("cdp_endpoint")
        if not request_cdp_endpoint and isinstance(
            self.runtime().recovery.snapshot().last_request, dict
        ):
            request_cdp_endpoint = (
                self.runtime().recovery.snapshot().last_request.get("cdp_endpoint")
            )
        cdp_endpoint = self.normalize_endpoint(
            request_cdp_endpoint or self.env("FAPAI_CDP_ENDPOINT") or ""
        )
        if not cdp_endpoint:
            return {
                "refreshed": False,
                "reason": "cdp_endpoint_not_configured",
                "path": snapshot_path,
            }
        if not self.permitted(cdp_endpoint):
            return {"refreshed": False, "reason": "cdp_endpoint_not_permitted"}

        cookies = self.export(cdp_endpoint)
        summary = self.summarize(cookies)
        sample_urls = self.sample_urls(payload)
        health = self.health(
            cookies,
            sample_urls,
            cdp_endpoint=cdp_endpoint,
        )
        cookie_count = int(cast("str | int", summary.get("count") or 0))
        if not health.get("healthy"):
            return {
                "refreshed": False,
                "reason": "cookie_snapshot_candidate_unhealthy",
                "path": snapshot_path,
                "cdp_endpoint": cdp_endpoint,
                "cookie_count": cookie_count,
                "health": health,
            }

        self.write(cookies, snapshot_path)
        return {
            "refreshed": True,
            "path": snapshot_path,
            "cdp_endpoint": cdp_endpoint,
            "cookie_count": cookie_count,
            "domains": summary.get("domains") or [],
            "shape_fingerprint": summary.get("shape_fingerprint"),
            "value_fingerprint": summary.get("value_fingerprint"),
            "health": health,
        }

    def _auth_cookie_snapshot_retry_attempts(
        self,
    ) -> int:
        raw = self.env("FAPAI_AUTH_COOKIE_RETRY_ATTEMPTS", "3")
        try:
            value = int(str(raw or "").strip())
        except ValueError:
            value = 3
        return max(1, min(value, 10))

    def _auth_cookie_snapshot_retry_backoff_seconds(
        self,
    ) -> float:
        raw = self.env("FAPAI_AUTH_COOKIE_RETRY_BACKOFF_SECONDS", "2")
        try:
            value = float(str(raw or "").strip())
        except ValueError:
            value = 2.0
        return max(0.0, min(value, 300.0))

    def _auth_cookie_snapshot_runtime_status(
        self,
    ) -> dict[str, object]:
        return self.state().snapshot()

    def _set_auth_cookie_snapshot_state(self, **updates: object) -> dict[str, object]:
        return self.state().update(updates)

    def _auth_cookie_snapshot_runtime_state(self) -> AuthCookieSnapshotState:
        return self.runtime().cookie_snapshot
