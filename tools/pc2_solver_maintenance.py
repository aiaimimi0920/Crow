"""Bounded maintenance navigation that retains pages for the next solve."""

from typing import Any, TypeGuard, cast

from src.captcha_deferral import TargetNavigationUnconfirmed


def valid_target_directory(value: object) -> TypeGuard[list[dict[str, object]]]:
    """Only a complete target directory can establish that a page disappeared."""
    return isinstance(value, list) and all(
        isinstance(tab, dict)
        and isinstance(tab.get("id"), str)
        and bool(tab["id"].strip())
        and isinstance(tab.get("type"), str)
        and bool(tab["type"].strip())
        and (tab["type"] != "page" or isinstance(tab.get("url"), str))
        for tab in value
    )


def pending_navigation_probe(value: object) -> TypeGuard[dict[str, object]]:
    return bool(
        isinstance(value, dict)
        and value.get("_navigation_unconfirmed") is True
        and isinstance(value.get("_target_id"), str)
        and value["_target_id"].strip()
    )


def bind_pending_navigation(
    probe: object, challenge_id: object
) -> dict[str, object] | None:
    if pending_navigation_probe(probe):
        return {**probe, "_challenge_id": str(challenge_id or "").strip()}
    return probe if isinstance(probe, dict) else None


class MaintenanceNavigationUnconfirmed(TargetNavigationUnconfirmed):
    """Carry only this maintenance operation's known-created page identity."""

    def __init__(self, opener: Any) -> None:
        super().__init__()
        self.probe_target: dict[str, object] | None = None
        target_id = getattr(opener, "target_id", None)
        if isinstance(target_id, str) and target_id.strip() in getattr(
            opener, "_opened_target_ids", ()
        ):
            self.probe_target = {
                "_target_id": target_id.strip(),
                "_target_url": opener.target_url,
                "_target_ws_url": getattr(opener, "target_ws_url", ""),
                "_target_cdp_endpoint": opener.cdp_endpoint,
                "_navigation_unconfirmed": True,
            }

    def result(self, scope: str, *, closed: int = 0) -> dict[str, object]:
        return {
            "attempted": True,
            "opened": False,
            "closed": closed,
            "scope": scope,
            "reason": "target_navigation_unconfirmed",
            "probe_target": self.probe_target,
        }


def pending_navigation_request_matches(opener: Any, pending: object) -> bool:
    if not pending_navigation_probe(pending):
        return False
    if str(pending.get("_target_cdp_endpoint") or "").rstrip("/") != str(
        opener.cdp_endpoint
    ).rstrip("/"):
        return False
    route = opener._solver_target_route(opener.target_url)
    return bool(
        route and opener._solver_target_route(pending.get("_target_url")) == route
    )


def pending_navigation_target_present(
    opener: Any, tabs: list[dict[str, object]], pending: object
) -> bool:
    """A fresh exact-ID blank page is pending, not missing or authenticated."""
    if not pending_navigation_probe(pending) or not pending_navigation_request_matches(
        opener, pending
    ):
        return False
    return any(
        isinstance(tab, dict)
        and tab.get("type") == "page"
        and tab.get("id") == pending["_target_id"]
        and str(tab.get("url") or "").strip() in {"", "about:blank"}
        for tab in tabs
    )


def open_maintenance_target(opener: Any) -> dict[str, object] | None:
    """Share one deadline across creation and confirmation, retaining the page."""
    from src.captcha_budget import SolveBudget, SolveStopped

    budget = SolveBudget()
    try:
        with budget.scope(opener):
            try:
                if opener._stop_if_cancelled():
                    raise SolveStopped(opener.last_failure_reason)
                opened = opener._open_target_tab()
                if opener._stop_if_cancelled():
                    raise SolveStopped(opener.last_failure_reason)
                return cast("dict[str, object] | None", opened)
            except TargetNavigationUnconfirmed as deferred:
                if opener._stop_if_cancelled():
                    raise SolveStopped(opener.last_failure_reason) from None
                opener.last_failure_reason = deferred.reason
                raise MaintenanceNavigationUnconfirmed(opener) from None
            except SolveStopped:
                # A helper can signal stop before polling the shared budget.
                # Mark it stopped so scope cleanup also preserves the page.
                budget.reason = budget.reason or "deadline_exceeded"
                raise
    finally:
        opener._close_solver_ws()
