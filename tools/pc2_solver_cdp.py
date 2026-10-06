from __future__ import annotations

import json
from importlib import import_module
from typing import Protocol, cast
from urllib.parse import parse_qsl, urlsplit

from src.collection.adapters.taobao_solver_target import _split_web_target_url
from tools.internal_api_http import fetch_json
from tools.pc2_solver_scope_policy import (
    _challenge_scope_for_url,
    solver_request_target_url,
    solver_request_target_urls,
)
from tools.pc2_solver_transport import log_event


class ProbeSocket(Protocol):
    def send(self, payload: str) -> object: ...

    def recv(self) -> str | bytes: ...


class ProbeSolver(Protocol):
    def _solver_target_route(self, value: object) -> str: ...

    def _normalize_target_url(self, value: object) -> str: ...

    def _is_manual_challenge_url(self, value: object) -> bool: ...

    def _remember_target_tab(self, tab: dict[str, object]) -> None: ...

    def _connect_to_target(self, target_ws: str, target_title: str) -> bool: ...

    def _page_challenge_summary(self) -> dict[str, object]: ...

    def _close_solver_ws(self) -> None: ...


def _create_probe_solver(
    *, cdp_endpoint: str, target_url: str | None = None
) -> ProbeSolver:
    from src.captcha_solver import CaptchaSolver

    return cast(
        ProbeSolver, CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
    )


def get_cdp_page_url(cdp_endpoint: str) -> str | None:
    """Get the URL of the first page tab from CDP."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list):
            return None
        for tab in tabs:
            if tab.get("type") == "page":
                url = str(tab.get("url") or "").strip()
                if url:
                    return url
        if tabs:
            url = str(tabs[0].get("url") or "").strip()
            if url:
                return url
        return None
    except Exception:  # noqa: BLE001 -- a failed CDP probe remains inconclusive
        return None


def _challenge_target_matches_request(
    solver: ProbeSolver, target_url: str | None, tab_url: object
) -> bool:
    requested = solver._solver_target_route(target_url)
    candidate = solver._solver_target_route(tab_url)
    if requested == candidate:
        return True
    if _challenge_scope_for_url(
        target_url
    ) != "seed" or not solver._is_manual_challenge_url(tab_url):
        return False
    # The site may omit list parameters on its challenge redirect. This fallback
    # locates that challenge only; authenticated-page matching remains exact.
    expected, redirected = urlsplit(requested), urlsplit(candidate)
    return not redirected.query and (
        expected.scheme,
        expected.netloc,
        expected.path,
    ) == (redirected.scheme, redirected.netloc, redirected.path)


def check_cdp_browser_for_challenge_page(
    cdp_endpoint: str, target_url: str | None = None
) -> dict[str, object] | None:
    """Find an existing challenge target using metadata, then fail-closed DOM evidence."""
    solver = None
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list) or not tabs:
            return None
        page_tabs = [
            tab
            for tab in tabs
            if isinstance(tab, dict)
            and tab.get("type") == "page"
            and str(tab.get("webSocketDebuggerUrl") or "").strip()
        ]
        requested_route = None
        if target_url:
            solver = _create_probe_solver(
                cdp_endpoint=cdp_endpoint, target_url=target_url
            )
            requested_route = solver._solver_target_route(target_url)
        candidates = []
        for tab in page_tabs:
            url = str(tab.get("url") or "")
            title = str(tab.get("title") or "").strip().lower()
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            path = parsed.path.lower()
            query_keys = {
                key.lower()
                for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
            }
            parsed_web = _split_web_target_url(url)
            is_challenge = (
                "/_____tmd_____/punish" in path
                or "x5secdata" in query_keys
                or (
                    parsed_web is not None
                    and parsed_web.hostname == "sec.taobao.com"
                    and "punish" in path
                )
                or ("验证码" in title and "拦截" in title)
            )
            if is_challenge:
                candidates.append(tab)
        if requested_route and solver is not None:
            candidates = [
                tab
                for tab in candidates
                if _challenge_target_matches_request(solver, target_url, tab.get("url"))
            ]
        if candidates:
            tab = candidates[0]
            return {
                "_target_id": str(tab.get("id") or "").strip(),
                "_target_url": str(tab.get("url") or "").strip(),
                "_target_ws_url": str(tab.get("webSocketDebuggerUrl") or "").strip(),
            }

        if solver is None:
            solver = _create_probe_solver(
                cdp_endpoint=cdp_endpoint, target_url=target_url
            )
        dom_candidates = page_tabs
        if requested_route:
            dom_candidates = [
                tab
                for tab in page_tabs
                if solver._solver_target_route(tab.get("url")) == requested_route
            ]
        for tab in dom_candidates:
            try:
                solver._remember_target_tab(tab)
                if not solver._connect_to_target(
                    str(tab.get("webSocketDebuggerUrl") or ""),
                    str(tab.get("title") or ""),
                ):
                    continue
                summary = solver._page_challenge_summary()
                evidence = [
                    key
                    for key in (
                        "challengePresent",
                        "explicitFailure",
                        "hardBlock",
                        "hasSlider",
                    )
                    if summary.get(key) is True
                ]
                if evidence:
                    return {
                        "_target_id": str(tab.get("id") or "").strip(),
                        "_target_url": str(tab.get("url") or "").strip(),
                        "_target_ws_url": str(
                            tab.get("webSocketDebuggerUrl") or ""
                        ).strip(),
                        "_challenge_evidence": evidence,
                    }
            except Exception as error:  # noqa: BLE001 -- isolate each failed target probe
                log_event(
                    {
                        "kind": "cdp_challenge_probe_target_error",
                        "target_id": str(tab.get("id") or "").strip(),
                        "error_type": type(error).__name__,
                    }
                )
                continue
            finally:
                solver._close_solver_ws()
        return None
    except Exception as error:  # noqa: BLE001 -- preserve the inconclusive probe contract
        log_event(
            {
                "kind": "cdp_challenge_probe_error",
                "error_type": type(error).__name__,
            }
        )
        return None
    finally:
        if solver is not None:
            solver._close_solver_ws()


def match_solver_request_target_url(
    last_request: object, selected_target_url: object, cdp_endpoint: str
) -> str:
    """Revalidate the probed request route against the latest control-plane state."""
    candidates: list[str] = solver_request_target_urls(last_request)
    if not candidates:
        return ""
    selected_target_url = str(selected_target_url or "").strip()
    if not selected_target_url:
        return candidates[0]
    if selected_target_url in candidates:
        return selected_target_url
    solver = _create_probe_solver(
        cdp_endpoint=cdp_endpoint, target_url=selected_target_url
    )
    selected_route = solver._solver_target_route(selected_target_url)
    if not selected_route:
        return ""
    for candidate in candidates:
        if solver._solver_target_route(candidate) == selected_route:
            return candidate
    return ""


def check_cdp_browser_for_authenticated_target(
    cdp_endpoint: str, target_url: str
) -> dict[str, object] | None:
    """Confirm that an existing target page is healthy without opening a new tab."""
    target_url = str(target_url or "").strip()
    if not target_url:
        return None
    solver = _create_probe_solver(cdp_endpoint=cdp_endpoint, target_url=target_url)
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list):
            return None
        normalized_target = solver._normalize_target_url(target_url)
        requested_route = solver._solver_target_route(target_url)
        page_tabs = []
        exact_tabs = []
        route_tabs = []
        for tab in tabs:
            if not isinstance(tab, dict) or tab.get("type") != "page":
                continue
            tab_url = str(tab.get("url") or "").strip()
            if not tab_url or not tab.get("webSocketDebuggerUrl"):
                continue
            page_tabs.append(tab)
            normalized_tab = solver._normalize_target_url(tab_url)
            if normalized_tab == normalized_target:
                exact_tabs.append(tab)
            elif (
                requested_route
                and solver._solver_target_route(tab_url) == requested_route
            ):
                route_tabs.append(tab)
        scoped_tabs = exact_tabs + route_tabs
        # Auction completion requires this target, not another tab's session.
        if (
            _challenge_scope_for_url(target_url) in {"seed", "detail"}
            and not scoped_tabs
        ):
            return None
        target_scoped = bool(scoped_tabs)
        candidates = scoped_tabs or page_tabs
        if not candidates:
            return None

        healthy_target: dict[str, object] | None = None
        for tab in candidates:
            solver._remember_target_tab(tab)
            if not solver._connect_to_target(
                str(tab.get("webSocketDebuggerUrl") or ""),
                str(tab.get("title") or ""),
            ):
                return None
            try:
                summary = solver._page_challenge_summary()
            finally:
                solver._close_solver_ws()
            if (
                summary.get("challengePresent") is True
                or summary.get("loginRequired") is True
                or summary.get("explicitFailure") is True
                or summary.get("hardBlock") is True
            ):
                return None
            if summary.get("authenticatedPage") is True and healthy_target is None:
                healthy_target = {
                    "_target_id": str(tab.get("id") or "").strip(),
                    "_target_url": str(tab.get("url") or "").strip(),
                }
            elif target_scoped and summary.get("authenticatedPage") is not True:
                return None
        return healthy_target
    except Exception:  # noqa: BLE001 -- probe failures cannot establish authentication
        return None
    finally:
        solver._close_solver_ws()


def check_cdp_browser_for_slider(
    cdp_endpoint: str, target_url: str | None = None
) -> dict[str, object] | None:
    """Lightweight CDP check: probe browser tabs for a visible NC slider.
    Returns the slider_info dict if found, or None."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
        if not isinstance(tabs, list) or not tabs:
            return None
        websocket = import_module("websocket")

        js = r"""
        (function() {
            var selectors = ['#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]', '.btn_slide', '.nc_iconfont.btn_slide', '#nc_1_n1t', '#nc_2_n1t', '.nc-slider-btn'];
            for (var i = 0; i < selectors.length; i++) {
                var el = document.querySelector(selectors[i]);
                if (el && el.offsetParent !== null) {
                    var r = el.getBoundingClientRect();
                    if (r.width > 5 && r.height > 5) return {found:true, x:r.left, y:r.top, width:r.width, height:r.height, selector:selectors[i]};
                }
            }
            return {found:false};
        })()
        """

        challenge_tabs = []
        page_tabs = []
        other_tabs = []
        for tab in tabs:
            if not isinstance(tab, dict) or not tab.get("webSocketDebuggerUrl"):
                continue
            url = str(tab.get("url") or "")
            try:
                path = urlsplit(url).path.lower()
            except ValueError:
                path = ""
            parsed = _split_web_target_url(url)
            if "/_____tmd_____/" in path or (
                parsed is not None
                and parsed.hostname in {"sec.taobao.com", "login.taobao.com"}
            ):
                challenge_tabs.append(tab)
            elif tab.get("type") == "page":
                page_tabs.append(tab)
            elif tab.get("type") == "iframe":
                other_tabs.append(tab)

        requested_route = None
        if target_url:
            solver = _create_probe_solver(
                cdp_endpoint=cdp_endpoint, target_url=target_url
            )
            requested_route = solver._solver_target_route(target_url)
            if requested_route:
                challenge_tabs = [
                    tab
                    for tab in challenge_tabs
                    if _challenge_target_matches_request(
                        solver, target_url, tab.get("url")
                    )
                ]
        for target in challenge_tabs + page_tabs + other_tabs:
            ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
            ws = None
            try:
                ws = websocket.create_connection(
                    ws_url, suppress_origin=True, timeout=5
                )
                ws.settimeout(5)
                send_id = 0

                def _send(
                    method: str,
                    params: dict[str, object] | None = None,
                    socket: ProbeSocket = ws,
                ) -> object:
                    nonlocal send_id
                    send_id += 1
                    mid = send_id
                    msg = {"id": mid, "method": method, "params": params or {}}
                    socket.send(json.dumps(msg))
                    while True:
                        resp = json.loads(socket.recv())
                        if resp.get("id") == mid:
                            return resp.get("result")

                _send("Runtime.enable")
                ret = _send(
                    "Runtime.evaluate", {"expression": js, "returnByValue": True}
                )
                value = (
                    ret.get("result", {}).get("value", {})
                    if isinstance(ret, dict)
                    else {}
                )
                if isinstance(value, dict) and value.get("found"):
                    slider_info = dict(value)
                    slider_info.update(
                        {
                            "_target_id": str(target.get("id") or "").strip(),
                            "_target_url": str(target.get("url") or "").strip(),
                            "_target_ws_url": ws_url,
                        }
                    )
                    return slider_info
            except Exception as error:  # noqa: BLE001 -- continue probing other targets
                log_event(
                    {
                        "kind": "cdp_slider_probe_target_error",
                        "target_id": str(target.get("id") or "").strip(),
                        "error_type": type(error).__name__,
                    }
                )
                continue
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001,S110 -- retain best-effort socket cleanup
                        pass
        return None
    except Exception as error:  # noqa: BLE001 -- preserve the inconclusive probe contract
        log_event(
            {
                "kind": "cdp_slider_probe_error",
                "error_type": type(error).__name__,
            }
        )
        return None


__all__ = (
    "_challenge_target_matches_request",
    "check_cdp_browser_for_authenticated_target",
    "check_cdp_browser_for_challenge_page",
    "check_cdp_browser_for_slider",
    "get_cdp_page_url",
    "match_solver_request_target_url",
    "solver_request_target_url",
    "solver_request_target_urls",
)
