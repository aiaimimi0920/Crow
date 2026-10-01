from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import parse_qs, quote, urlsplit

import requests
import websocket

from src.project_environment import getenv as project_getenv

from .captcha_context import browser_identity_init_script, build_user_agent_override
from .collection.adapters.taobao_solver_target import _is_taobao_target, _split_web_target_url

logger = logging.getLogger(__name__)


def _has_solver_url_flag(value, name):
    try:
        query = urlsplit(str(value or "")).query
    except ValueError:
        return False
    return parse_qs(query, keep_blank_values=True).get(name) == ["1"]


class CaptchaCDPMixin:
    def _open_target_tab(self):
        target_url = self._normalize_target_url(self.target_url)
        if not target_url:
            return None
        identity_first = self._target_requires_identity_before_navigation(target_url)
        opened_url = "about:blank" if identity_first else target_url
        last_error = None
        for timeout in (5, 8, 12):
            timeout = self._bounded_io_timeout(timeout)
            try:
                response = requests.put(
                    f"{self.cdp_endpoint}/json/new?{quote(opened_url, safe='/:%-._~')}",
                    timeout=timeout,
                )
                payload = response.json()
                if isinstance(payload, dict):
                    self._remember_target_tab(payload)
                    target_id = str(payload.get("id") or "").strip()
                    if target_id:
                        self._opened_target_ids.add(target_id)
                    if identity_first and not self._prepare_opened_target_before_navigation(
                        payload,
                        target_url,
                    ):
                        last_error = RuntimeError("identity-first target preparation failed")
                        continue
                    return payload
            except Exception as error:
                last_error = error
        if last_error is not None:
            logger.warning("[SOLVER] Failed to open target tab: %s", last_error)
        return None

    def _connect_to_target(self, target_ws, target_title):
        # Resolve configuration before opening or closing a socket. Alias conflicts
        # are configuration errors, not recoverable transport failures.
        configured_user_agent = str(project_getenv("CROW_BROWSER_USER_AGENT") or "").strip()
        configured_full_version = (
            str(project_getenv("CROW_BROWSER_IDENTITY_FULL_VERSION") or "").strip()
            if configured_user_agent else ""
        )
        disable_stealth = project_getenv("CROW_SOLVER_DISABLE_STEALTH", "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        try:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
            target_ws = self._rewrite_ws_url(target_ws)
            if target_ws:
                self.target_ws_url = target_ws
            logger.info("[SOLVER] Connecting to tab: %s", target_title)
            self.ws = websocket.create_connection(target_ws, suppress_origin=True, timeout=self._bounded_io_timeout(5))
            self.ws.settimeout(self._bounded_io_timeout(5))
            # This solver uses direct Runtime.evaluate/Page commands and consumes
            # no DOM, Runtime, or Page events. Avoid subscribing those domains on
            # a live challenge page; the subscriptions are unnecessary CDP noise.
            connection_probe = self._send_cdp(
                "Runtime.evaluate",
                {
                    "expression": "void 0",
                    "returnByValue": True,
                    "silent": True,
                },
            )
            if connection_probe is None:
                raise RuntimeError("CDP target websocket probe failed")

            if configured_user_agent:
                if not configured_full_version:
                    version_match = re.search(
                        r"(?:Chrome|Chromium)/(\d+(?:\.\d+){1,3})",
                        configured_user_agent,
                    )
                    configured_full_version = (
                        version_match.group(1) if version_match else "151.0.0.0"
                    )
                self._send_cdp(
                    "Emulation.setUserAgentOverride",
                    build_user_agent_override(
                        configured_user_agent,
                        configured_full_version,
                    ),
                )
                self._send_cdp(
                    "Emulation.setTimezoneOverride",
                    {"timezoneId": "Asia/Shanghai"},
                )
                self._send_cdp(
                    "Emulation.setLocaleOverride",
                    {"locale": "zh-CN"},
                )

            # CDP Stealth Injection: Hide automation fingerprints
            stealth_js = browser_identity_init_script()
            if not disable_stealth:
                self._send_cdp("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
                # The challenge page is already loaded; also patch the current document.
                self._send_cdp("Runtime.evaluate", {"expression": stealth_js, "returnByValue": True})

            preflight_identity = self._send_cdp(
                "Runtime.evaluate",
                {
                    "expression": """(() => ({
                        platform: navigator.platform,
                        uaPlatform: navigator.userAgentData && navigator.userAgentData.platform,
                        webdriver: navigator.webdriver,
                        languages: Array.from(navigator.languages || []),
                        hardwareConcurrency: navigator.hardwareConcurrency,
                        deviceMemory: navigator.deviceMemory,
                        maxTouchPoints: navigator.maxTouchPoints,
                        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    }))()""",
                    "returnByValue": True,
                },
            )
            preflight_value = (
                preflight_identity.get("result", {}).get("value", {})
                if isinstance(preflight_identity, dict)
                else {}
            )
            if isinstance(preflight_value, dict):
                logger.info(
                    "[SOLVER] Browser identity preflight "
                    f"platform={preflight_value.get('platform')} "
                    f"ua_platform={preflight_value.get('uaPlatform')} "
                    f"webdriver={preflight_value.get('webdriver')} "
                    f"languages={preflight_value.get('languages')} "
                    f"hardware={preflight_value.get('hardwareConcurrency')}/"
                    f"{preflight_value.get('deviceMemory')}/"
                    f"{preflight_value.get('maxTouchPoints')} "
                    f"timezone={preflight_value.get('timezone')}"
                )

            return True
        except Exception as e:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
            self.ws = None
            if self._is_manual_challenge_url(self.current_target_url):
                self.last_failure_reason = "manual_required"
            logger.warning("[SOLVER] WS Connection failed: %s", e)
            return False

    def _send_cdp(self, method, params=None):
        if not self.ws: return None
        if self._stop_if_cancelled():
            return None

        msg = {
            "id": self.message_id,
            "method": method,
            "params": params or {}
        }

        try:
            if getattr(self, "_solve_budget", None) is not None:
                self.ws.settimeout(self._bounded_io_timeout(5))
            self.ws.send(json.dumps(msg))
            self.message_id += 1
            start_time = time.time()
            timeout_seconds = 12 if "captureScreenshot" in method else 5
            while time.time() - start_time < timeout_seconds:
                if self._stop_if_cancelled():
                    return None
                try:
                    if getattr(self, "_solve_budget", None) is not None:
                        self.ws.settimeout(self._bounded_io_timeout(timeout_seconds))
                    res = self.ws.recv()
                    res_json = json.loads(res)
                    if res_json.get("id") == msg["id"]:
                        if "error" in res_json:
                            logger.error("[SOLVER] CDP Error method=%s error=%s", method, res_json["error"])
                            return None
                        return res_json.get("result")
                except websocket.WebSocketTimeoutException:
                    logger.warning("[SOLVER] Timeout waiting for %s", method)
                    return None
                except Exception as e:
                    logger.warning("[SOLVER] Error receiving response method=%s: %s", method, e)
                    return None
        except Exception as e:
            logger.error("[SOLVER] CDP Send Error method=%s: %s", method, e)
            return None

        return None

    def connect_tab(self):
        """Connect to the background worker tab using explicit URL parameters."""
        tabs = self._get_json("list")
        if tabs is None:
            if self.target_ws_url:
                logger.info("[SOLVER] CDP target list unavailable; reusing cached target websocket.")
                if self._connect_to_target(self.target_ws_url, "cached solver target"):
                    return True
                logger.warning("[SOLVER] Cached target websocket failed; CDP target list is unavailable.")
            logger.warning("[SOLVER] CDP target list unavailable on %s.", self.cdp_endpoint)
            return False

        if self.target_ws_url:
            pruning = self._prune_duplicate_challenge_tabs(tabs)
            if pruning.get("closed"):
                refreshed_tabs = self._get_json("list")
                if isinstance(refreshed_tabs, list):
                    tabs = refreshed_tabs
            logger.info("[SOLVER] Reusing cached target websocket.")
            if self._connect_to_target(self.target_ws_url, "cached solver target"):
                return True
            logger.warning("[SOLVER] Cached target websocket failed; falling back to CDP discovery.")

        compaction = self._compact_cdp_pages_if_needed(
            tabs,
            reserve_for_new_page=bool(self._normalize_target_url(self.target_url)),
        )
        if compaction.get("triggered"):
            tabs = self._get_json("list")
            if tabs is None:
                tabs = []

        if not tabs:
            normalized_target_url = self._normalize_target_url(self.target_url)
            if not normalized_target_url:
                logger.warning("[SOLVER] No Chrome/Edge debug sessions found on port %s.", self.port)
                return False
            opened_target = self._open_target_tab()
            if not isinstance(opened_target, dict):
                logger.warning("[SOLVER] No Chrome/Edge debug sessions found on port %s.", self.port)
                return False
            target_ws = opened_target.get("webSocketDebuggerUrl")
            target_title = str(opened_target.get("title") or "")
            logger.info("[SOLVER] Opened requested solver target: %s", normalized_target_url)
            return self._connect_to_target(target_ws, target_title)

        pruning = self._prune_duplicate_challenge_tabs(tabs)
        kept_challenge_target_id = str(pruning.get("kept") or "").strip()
        if pruning.get("closed") or self.target_id:
            refreshed_tabs = self._get_json("list")
            if isinstance(refreshed_tabs, list):
                tabs = refreshed_tabs

        target_ws = None
        target_title = ""
        normalized_target_url = self._normalize_target_url(self.target_url)

        # Priority 0: exact requested target URL
        if normalized_target_url:
            for tab in tabs:
                url = self._normalize_target_url(tab.get("url", ""))
                if url == normalized_target_url:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    logger.info("[SOLVER] Found requested solver target: %s", url)
                    break
            if not target_ws and kept_challenge_target_id:
                for tab in tabs:
                    if str(tab.get("id") or "").strip() != kept_challenge_target_id:
                        continue
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    logger.info("[SOLVER] Reusing the unique challenge target for this collection scope.")
                    break
            if not target_ws and self.target_id:
                for tab in tabs:
                    if str(tab.get("id") or "") == self.target_id:
                        self._remember_target_tab(tab)
                        target_ws = tab.get("webSocketDebuggerUrl")
                        target_title = tab.get("title", "")
                        logger.info("[SOLVER] Recovered cached solver target by id: %s", self.target_id)
                        break
            if not target_ws:
                for tab in tabs:
                    if (
                        self._is_manual_challenge_url(tab.get("url"))
                        and self._manual_challenge_matches_requested_target(tab.get("url"))
                    ):
                        self._remember_target_tab(tab)
                        target_ws = tab.get("webSocketDebuggerUrl")
                        target_title = tab.get("title", "")
                        logger.info("[SOLVER] Reusing existing manual challenge target.")
                        break
            if not target_ws:
                if self.target_id:
                    logger.info("[SOLVER] Cached solver target %s no longer present; reopening requested target.", self.target_id)
                    self.target_id = None
                    self.target_ws_url = None
                compaction = self._compact_cdp_pages_if_needed(tabs, reserve_for_new_page=True)
                if compaction.get("triggered"):
                    tabs = self._get_json("list") or []
                opened_target = self._open_target_tab()
                if isinstance(opened_target, dict):
                    target_ws = opened_target.get("webSocketDebuggerUrl")
                    target_title = str(opened_target.get("title") or "")
                    logger.info("[SOLVER] Opened requested solver target: %s", normalized_target_url)

        # Priority 1: 100% targeted background worker currently solving
        if not target_ws:
            requested_scope = self._solver_target_scope(self.target_url)
            for tab in tabs:
                url = tab.get("url", "")
                if _has_solver_url_flag(url, "__captcha_solver_bg"):
                    if requested_scope and self._solver_target_scope(url) != requested_scope:
                        continue
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    logger.info("[SOLVER] Found dedicated worker (solving): %s", url)
                    break

        # Priority 2: 100% targeted background worker in standby mode (useful if it's stuck or just transitioned)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                if _has_solver_url_flag(url, "__captcha_worker_master"):
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    logger.info("[SOLVER] Found dedicated worker (standby): %s", url)
                    break

        # Priority 2.5: sec.taobao.com / login.taobao.com pages (common captcha redirect destination)
        if not target_ws:
            for tab in tabs:
                url = tab.get("url", "")
                parsed = _split_web_target_url(url)
                if parsed is not None and parsed.hostname in {"sec.taobao.com", "login.taobao.com"}:
                    self._remember_target_tab(tab)
                    target_ws = tab.get("webSocketDebuggerUrl")
                    target_title = tab.get("title", "")
                    logger.info("[SOLVER] Found sec/login page (likely captcha redirect): %s", url)
                    break

        # Priority 3: Fallback to old heuristic
        if not target_ws:
            priority_keywords = ["验证", "RGV587", "司法", "淘宝", "tmall", "taobao"]
            for kw in priority_keywords:
                for tab in tabs:
                    url = tab.get("url", "")
                    title = tab.get("title", "")
                    # Brand text in a path/query is not evidence of site identity.
                    parsed = _split_web_target_url(url)
                    url_hint = url
                    if kw in {"tmall", "taobao"}:
                        url_hint = parsed.hostname if _is_taobao_target(parsed) else ""
                    if kw in title or kw in url_hint:
                        self._remember_target_tab(tab)
                        target_ws = tab.get("webSocketDebuggerUrl")
                        target_title = title
                        break
                if target_ws: break

        if not target_ws:
             logger.warning("[SOLVER] No relevant debug tag found.")
             # Let's see what tabs are open just for debugging
             logger.info("[SOLVER] Currently open tabs:")
             for t in tabs[:5]:
                 logger.info("  - %s | %s", t.get("title", "")[:30], t.get("url", "")[:50])
             return False

        return self._connect_to_target(target_ws, target_title)

    def _activate_target_tab(self):
        """Activate the exact CDP target before any physical mouse operation."""
        self._target_activation_verified = False
        target_id = str(self.target_id or "").strip()
        if not target_id:
            return False
        last_error = None
        for timeout in (2, 4, 6):
            timeout = self._bounded_io_timeout(timeout)
            try:
                response = requests.get(
                    f"{self.cdp_endpoint}/json/activate/{quote(target_id, safe='')}",
                    timeout=timeout,
                )
                if response.status_code < 400:
                    self._target_activation_verified = True
                    return True
                last_error = RuntimeError(f"CDP target activation returned HTTP {response.status_code}")
            except Exception as error:
                last_error = error
        if last_error is not None:
            logger.warning("[SOLVER] Failed to activate target tab %s: %s", target_id, last_error)
        return False

    def _bring_to_front(self):
        """Bring the exact captcha tab forward so OS mouse input hits that tab."""
        activated = self._activate_target_tab()
        if activated:
            self._wait_interruptibly(0.15)
            return True
        try:
            brought_to_front = self._send_cdp("Page.bringToFront") is not None
            # Best-effort focus; some Chromium builds still need explicit window focus.
            focused = self._send_cdp("Runtime.evaluate", {
                "expression": "try { window.focus(); document.body && document.body.focus && document.body.focus(); } catch(e) {}",
                "returnByValue": True
            }) is not None
            self._wait_interruptibly(0.15)
            return bool(brought_to_front or focused)
        except Exception as e:
            logger.warning("[SOLVER] bringToFront failed: %s", e)
            return False


__all__ = ["CaptchaCDPMixin"]
