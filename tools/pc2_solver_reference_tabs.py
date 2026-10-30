"""Open user-requested reference sites after three completed, failed slider drags."""

import json
from urllib.parse import urlsplit

from tools.cdp_background_page import open_background_page
from tools.pc2_solver_state_store import FALLBACK_STATE_PATH, _load_fallback_state
from tools.pc2_solver_transport import log_event
from tools.taobao_login_health import list_cdp_targets

SITES = (
    ("google.com", "https://www.google.com/"),
    ("baidu.com", "https://www.baidu.com/"),
)


def site_present(targets, domain):
    for target in targets:
        if target.get("type") != "page":
            continue
        parsed = urlsplit(str(target.get("url") or ""))
        host = (parsed.hostname or "").lower()
        if parsed.scheme in {"http", "https"} and (
            host == domain or host.endswith("." + domain)
        ):
            return True
    return False


def load_reference_state():
    try:
        value = json.loads(
            FALLBACK_STATE_PATH.with_name("solver-reference-tabs.json").read_text(
                encoding="utf-8"
            )
        )
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_reference_state(state):
    path = FALLBACK_STATE_PATH.with_name("solver-reference-tabs.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(path)


def record_failed_drags(endpoint, failures, *, allow_open=True):
    try:
        challenge_id = _load_fallback_state().get("challenge_id")
        if not challenge_id:
            return
        state = load_reference_state()
        if state.get("challenge_id") != challenge_id:
            state = {"challenge_id": challenge_id, "failed_drags": 0}
        if failures <= 0:
            state["post_open_failures"] = 0
            save_reference_state(state)
            return
        count = int(state.get("failed_drags", 0)) + failures
        state["failed_drags"] = count
        if state.get("tabs_ready"):
            state["post_open_failures"] = int(state.get("post_open_failures", 0)) + 1
        save_reference_state(state)
        if count < 3 or not allow_open:
            return
        for domain, url in SITES:
            # Re-read after every creation; retries never knowingly duplicate a tab.
            if site_present(list_cdp_targets(endpoint), domain):
                continue
            open_background_page(endpoint, url)
            log_event(
                {
                    "kind": "solver_reference_tab_opened",
                    "site": domain,
                    "failed_drags": count,
                }
            )
        if not state.get("tabs_ready"):
            state.update(tabs_ready=True, post_open_failures=0)
            save_reference_state(state)
    except Exception as exc:  # noqa: BLE001 -- optional tabs must not change challenge outcome
        log_event(
            {"kind": "solver_reference_tab_error", "error_type": type(exc).__name__}
        )
