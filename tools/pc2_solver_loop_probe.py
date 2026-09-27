"""Discover one solver target while retaining request priority and probe events."""

import time
from typing import cast

from tools.pc2_solver_cdp import (
    _create_probe_solver,
    check_cdp_browser_for_challenge_page,
    check_cdp_browser_for_slider,
)
from tools.pc2_solver_retry_state import (
    SLIDER_RETRY_INTERVAL_SECONDS,
    SOLVER_COOLDOWN_FAIL_THRESHOLD,
    SOLVER_COOLDOWN_SECONDS,
)
from tools.pc2_solver_scope import check_cdp_healthy
from tools.pc2_solver_transport import (
    log_event,
    real_taobao_auto_solver_enabled,
    write_solver_heartbeat,
)


def prepare_solver_browser(
    api_base_url: str,
    cdp_endpoint: str,
    poll_seconds: float,
    max_attempts: int,
    expected_node_id: str | None,
) -> None:
    log_event(
        {
            "kind": "local_solver_boot",
            "api_base_url": api_base_url,
            "cdp_endpoint": cdp_endpoint,
            "poll_seconds": poll_seconds,
            "max_attempts": max_attempts,
            "expected_node_id": expected_node_id,
            "real_taobao_auto_solver_enabled": real_taobao_auto_solver_enabled(),
            "cooldown_fail_threshold": SOLVER_COOLDOWN_FAIL_THRESHOLD,
            "cooldown_seconds": SOLVER_COOLDOWN_SECONDS,
            "slider_retry_interval_seconds": SLIDER_RETRY_INTERVAL_SECONDS,
        }
    )
    write_solver_heartbeat("waiting_for_cdp")
    while not check_cdp_healthy(cdp_endpoint):
        write_solver_heartbeat("waiting_for_cdp")
        log_event({"kind": "waiting_for_cdp", "cdp_endpoint": cdp_endpoint})
        time.sleep(5)


def probe_requested_targets(
    cdp_endpoint: str,
    target_urls: list[str],
    *,
    periodic: bool,
    running: bool = False,
    paused: bool = False,
) -> tuple[dict[str, object] | None, str]:
    candidates: list[str | None] = list(target_urls) or [None]
    for candidate in candidates:
        slider = check_cdp_browser_for_slider(cdp_endpoint, target_url=candidate)
        if slider:
            log_event(
                {
                    "kind": "cdp_periodic_probe_slider_found"
                    if periodic
                    else "cdp_probe_slider_found",
                    "slider": slider,
                }
            )
            return cast("dict[str, object]", slider), str(candidate or "")
        if not periodic:
            route = _create_probe_solver(
                cdp_endpoint=cdp_endpoint, target_url=candidate
            )._solver_target_route(candidate)
            log_event(
                {
                    "kind": "cdp_probe_no_slider",
                    "running": running,
                    "paused": paused,
                    "requested_route": route,
                }
            )
        challenge = check_cdp_browser_for_challenge_page(
            cdp_endpoint, target_url=candidate
        )
        if challenge:
            if periodic:
                log_event(
                    {
                        "kind": "cdp_periodic_probe_challenge_page",
                        "cdp_endpoint": cdp_endpoint,
                    }
                )
            else:
                log_event({"kind": "cdp_probe_challenge_page", "target": challenge})
            return cast("dict[str, object]", challenge), str(candidate or "")
    return None, ""
