"""One bounded reference browsing phase, serialized after a completed solver child."""

import random
import time

from tools.pc2_reference_browser import ReferencePage
from tools.pc2_reference_navigation import safe_navigation
from tools.pc2_solver_manual_window import active_manual_window
from tools.pc2_solver_reference_tabs import load_reference_state, save_reference_state
from tools.pc2_solver_scope_policy import (
    select_solver_scope_status,
    solver_status_requires_manual_only,
)
from tools.pc2_solver_state_store import _load_fallback_state
from tools.pc2_solver_transport import (
    log_event,
    read_solver_status,
    write_solver_heartbeat,
)
from tools.taobao_login_health import activate_cdp_target, list_cdp_targets


def allowed(api, challenge_id):
    if active_manual_window():
        return False
    status = read_solver_status(api)
    if (
        not isinstance(status, dict)
        or status.get("error")
        or status.get("operator_paused")
    ):
        return False
    if status.get("pause_reason") in {"operator", "manual", "manual_required"}:
        return False
    selected = select_solver_scope_status(status, preferred_challenge_id=challenge_id)
    return (
        selected.get("challenge_id") == challenge_id
        and not selected.get("manual_required")
        and not selected.get("running")
        and not solver_status_requires_manual_only(selected)
    )


def maybe_browse_reference_tabs(api, endpoint, probe_target):
    pages = []
    original = None
    interrupted = False
    state = load_reference_state()
    challenge_id = _load_fallback_state().get("challenge_id")
    if (
        not challenge_id
        or state.get("challenge_id") != challenge_id
        or not state.get("tabs_ready")
        or state.get("browse_started")
        or type(state.get("post_open_failures")) is not int
        or state["post_open_failures"] < 2
    ):
        return
    try:
        if not allowed(api, challenge_id):
            return
        targets = list_cdp_targets(endpoint)
        target_id = (probe_target or {}).get("_target_id")
        original = next((t for t in targets if t.get("id") == target_id), None)
        if original is None:
            return
        references = []
        for host in ("google.com", "baidu.com"):
            from urllib.parse import urlsplit

            found = next(
                (
                    t
                    for t in targets
                    if t.get("type") == "page"
                    and safe_navigation(t.get("url"))
                    and urlsplit(t["url"]).hostname.removeprefix("www.") == host
                ),
                None,
            )
            if found is None:
                return
            references.append(found)
        duration = random.uniform(60, 120)
        state.update(browse_started=True, browse_duration_seconds=duration)
        save_reference_state(state)
        log_event(
            {
                "kind": "solver_reference_browse_started",
                "duration_seconds": round(duration, 1),
            }
        )
        deadline = time.monotonic() + duration
        for target in references:
            pages.append(ReferencePage(target))
            pages[-1].deadline = deadline
        next_page = 0
        while time.monotonic() < deadline:
            if not allowed(api, challenge_id):
                interrupted = True
                break
            if not any(t.get("id") == target_id for t in list_cdp_targets(endpoint)):
                interrupted = True
                break
            if time.monotonic() >= deadline:
                break
            write_solver_heartbeat("reference_browsing")
            index = next_page % len(pages)
            activate_cdp_target(endpoint, references[index])
            if not pages[index].step():
                interrupted = True
                break
            next_page += 1
            end = min(deadline, time.monotonic() + random.uniform(2, 5))
            while time.monotonic() < end:
                if active_manual_window():
                    interrupted = True
                    break
                time.sleep(min(0.5, max(0, end - time.monotonic())))
            if interrupted:
                break
    except Exception as exc:  # noqa: BLE001 -- optional browsing never changes solver outcome
        interrupted = True
        log_event(
            {"kind": "solver_reference_browse_error", "error_type": type(exc).__name__}
        )
    finally:
        for page in pages:
            try:
                page.close()
            except Exception:  # noqa: BLE001 -- optional cleanup
                log_event({"kind": "solver_reference_close_failed"})
        if state.get("browse_started"):
            state["browse_finished"] = True
            state["browse_interrupted"] = interrupted
            try:
                save_reference_state(state)
            except OSError:
                log_event({"kind": "solver_reference_receipt_failed"})
            # Never steal focus back from a newly active human session.
            try:
                if original and allowed(api, challenge_id):
                    current = list_cdp_targets(endpoint)
                    if any(t.get("id") == original["id"] for t in current):
                        activate_cdp_target(endpoint, original)
            except Exception:  # noqa: BLE001 -- disappearance must not activate another page
                log_event({"kind": "solver_reference_return_unavailable"})
            log_event(
                {"kind": "solver_reference_browse_finished", "interrupted": interrupted}
            )
