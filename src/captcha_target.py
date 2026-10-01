from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from src.project_environment import getenv as project_getenv

from .captcha_context import DEFAULT_CDP_PAGE_TARGET_LIMIT
from .captcha_pointer_backend import OSPointerBackend
from .collection.adapters.taobao_auth_target import SEED_IDENTITY_QUERY_KEYS
from .collection.adapters.taobao_solver_target import _split_web_target_url

logger = logging.getLogger(__name__)


class CaptchaTargetMixin:
    def __init__(self, port=9222, target_url=None, cdp_endpoint=None, cancel_checker=None,
                 *, pointer_backend: OSPointerBackend | None = None):
        self._pointer_backend_override = pointer_backend
        configured_endpoint = (cdp_endpoint or project_getenv("CROW_CDP_ENDPOINT") or "").strip()
        if configured_endpoint:
            self.cdp_endpoint = configured_endpoint.rstrip("/")
            parsed = urlsplit(self.cdp_endpoint)
            self.port = parsed.port or port
        else:
            self.port = port
            self.cdp_endpoint = f"http://localhost:{self.port}"
        self.target_url = target_url
        self.ws_url = None
        self.ws = None
        self.message_id = 1
        self.lock = threading.Lock()
        self.target_id = None
        self.target_ws_url = None
        self.current_target_url = None
        self._target_activation_verified = False
        self._linux_window_id = None
        self._uinput_handle = None
        self._uinput_ecodes = None
        self._opened_target_ids = set()
        self.last_failure_reason = None
        self._last_mock_terminal_state = None
        self.cancel_checker = cancel_checker

    def _cancel_requested(self):
        checker = getattr(self, "cancel_checker", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception as error:
            logger.exception("[SOLVER] Cancel checker failed")
            return False

    def _stop_if_cancelled(self):
        budget = getattr(self, "_solve_budget", None)
        stopped = budget.stopped(self._cancel_requested) if budget is not None else self._cancel_requested()
        if not stopped:
            return False
        logger.info("[SOLVER] Stop requested after manual resume/auth completion; exiting solver loop.")
        self.last_failure_reason = budget.reason if budget is not None else "cancelled"
        self._release_cdp_mouse()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        return True

    def _wait_interruptibly(self, seconds):
        budget = getattr(self, "_solve_budget", None)
        if budget is not None:
            budget.wait(seconds, self._cancel_requested)
        else:
            time.sleep(seconds)

    def _release_cdp_mouse(self):
        if not getattr(self, "_cdp_mouse_down", False) or not self.ws:
            return
        try:
            x, y = getattr(self, "_cdp_mouse_position", (0, 0))
            if callable(getattr(self.ws, "settimeout", None)):
                self.ws.settimeout(0.1)
            self.ws.send(json.dumps({"id": self.message_id, "method": "Input.dispatchMouseEvent",
                                    "params": {"type": "mouseReleased", "x": x, "y": y,
                                               "button": "left", "buttons": 0, "clickCount": 1}}))
            self.message_id += 1
        except Exception:
            pass
        finally:
            self._cdp_mouse_down = False

    def _bounded_io_timeout(self, seconds):
        from .captcha_budget import SolveStopped
        budget = getattr(self, "_solve_budget", None)
        if budget is None:
            return seconds
        if budget.stopped(self._cancel_requested):
            raise SolveStopped(budget.reason)
        return min(seconds, max(0.001, budget.remaining()))

    def _remember_target_tab(self, tab):
        if not isinstance(tab, dict):
            return
        target_id = str(tab.get("id") or "").strip()
        target_ws_url = str(tab.get("webSocketDebuggerUrl") or "").strip()
        target_url = str(tab.get("url") or "").strip()
        if target_id:
            if target_id != self.target_id:
                self._target_activation_verified = False
            self.target_id = target_id
        if target_ws_url:
            self.target_ws_url = target_ws_url
        if target_url:
            self.current_target_url = target_url

    def _get_json(self, endpoint):
        last_error = None
        for timeout in (2, 4, 6):
            timeout = self._bounded_io_timeout(timeout)
            try:
                resp = requests.get(f"{self.cdp_endpoint}/json/{endpoint}", timeout=timeout)
                return resp.json()
            except Exception as error:
                last_error = error
        if last_error is not None:
            logger.warning("[SOLVER] Failed to fetch /json/%s: %s", endpoint, last_error)
        return None

    def _page_target_limit(self):
        raw_limit = project_getenv("CROW_CDP_MAX_PAGE_TARGETS", str(DEFAULT_CDP_PAGE_TARGET_LIMIT)).strip()
        try:
            limit = int(raw_limit)
        except ValueError:
            return DEFAULT_CDP_PAGE_TARGET_LIMIT
        if limit <= 0:
            return DEFAULT_CDP_PAGE_TARGET_LIMIT
        return limit

    def _reset_current_target(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None
        self.target_id = None
        self.target_ws_url = None
        self.current_target_url = None
        self._linux_window_id = None

    @staticmethod
    def _is_login_url(value):
        target_url = str(value or "").strip()
        if not target_url:
            return False
        parsed_web = _split_web_target_url(target_url)
        if parsed_web is not None and parsed_web.hostname in {
            "login.taobao.com", "login.tmall.com",
        }:
            return True
        # Generic and local CAPTCHA harnesses also use login routes. Keep those
        # paths independent of Taobao host identity, without trusting query text.
        try:
            path = urlsplit(target_url).path.lower()
        except ValueError:
            return False
        return (
            "third-party-cookie" in path
            or "/passport/" in path
            or "/login_jump" in path
            or "/_____tmd_____/page/login" in path
        )

    @classmethod
    def _is_manual_challenge_url(cls, value):
        target_url = str(value or "").strip()
        if not target_url:
            return False
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return False
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        return (
            "/_____tmd_____/punish" in parsed.path.lower()
            or bool(query_keys & {"x5secdata", "x5step"})
            or cls._is_login_url(target_url)
        )

    @classmethod
    def _is_challenge_tab(cls, tab):
        if not isinstance(tab, dict):
            return False
        tab_url = str(tab.get("url") or "").strip()
        if cls._is_manual_challenge_url(tab_url):
            return True
        title = re.sub(r"\s+", " ", str(tab.get("title") or "")).strip().lower()
        return title in {
            "captcha verification",
            "验证码拦截",
            "安全验证",
        }

    def _close_cdp_target(self, target_id):
        target_id = str(target_id or "").strip()
        if not target_id:
            return False
        try:
            requests.get(
                f"{self.cdp_endpoint}/json/close/{quote(target_id, safe='')}",
                timeout=5,
            )
            return True
        except Exception as error:
            logger.warning("[SOLVER] Failed to close CDP target %s: %s", target_id, error)
            return False

    def _open_keepalive_tab(self):
        try:
            response = requests.put(f"{self.cdp_endpoint}/json/new?about:blank", timeout=5)
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("id") or "").strip() or None
        except Exception as error:
            logger.warning("[SOLVER] Failed to open keepalive tab before page compaction: %s", error)
        return None

    def _compact_cdp_pages_if_needed(self, tabs=None, reserve_for_new_page=False):
        if tabs is None:
            tabs = self._get_json("list")
        if not isinstance(tabs, list):
            return {"triggered": False, "page_count": 0, "closed": 0}

        page_targets = [
            tab
            for tab in tabs
            if isinstance(tab, dict) and str(tab.get("type") or "") == "page"
        ]
        page_count = len(page_targets)
        target_limit = self._page_target_limit()
        trigger_count = max(target_limit - 1, 1) if reserve_for_new_page else target_limit
        if page_count < trigger_count:
            return {"triggered": False, "page_count": page_count, "closed": 0}

        logger.info(
            f"[SOLVER] CDP page target count reached {page_count}; "
            "closing stale page targets before retrying current task."
        )
        keepalive_target_id = self._open_keepalive_tab()
        preserve_target_id = keepalive_target_id or str(page_targets[0].get("id") or "").strip()
        self._reset_current_target()
        closed = 0
        for tab in page_targets:
            target_id = tab.get("id")
            if str(target_id or "").strip() == preserve_target_id:
                continue
            if self._close_cdp_target(target_id):
                closed += 1
                self._opened_target_ids.discard(str(target_id or ""))
        self.target_id = None
        self.target_ws_url = None
        summary = {"triggered": True, "page_count": page_count, "closed": closed}
        if keepalive_target_id:
            summary["keepalive_target_id"] = keepalive_target_id
        elif preserve_target_id:
            summary["preserved_target_id"] = preserve_target_id
        return summary

    def _close_owned_target_tabs(self):
        budget = getattr(self, "_solve_budget", None)
        if budget is not None and budget.stopped(self._cancel_requested):
            # Keep tabs for manual recovery rather than extend an expired run with cleanup I/O.
            return 0
        owned_target_ids = [target_id for target_id in self._opened_target_ids if target_id]
        if not owned_target_ids:
            return 0
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

        closed = 0
        current_target_id = self.target_id
        for target_id in owned_target_ids:
            if self._close_cdp_target(target_id):
                closed += 1
            self._opened_target_ids.discard(target_id)
        if current_target_id in owned_target_ids:
            self.target_id = None
            self.target_ws_url = None
            self.current_target_url = None
        return closed

    def _prune_duplicate_challenge_tabs(self, tabs):
        """Keep only the active punish target before a solve attempt.

        Each collection scope owns one active challenge at a time. Failed
        requests and cooldown recovery can leave punish pages for older item
        routes in the shared browser profile; those pages may compete for the
        same challenge/session state. Preserve one page for the requested scope
        and close only duplicate pages in that scope. Login, normal auction
        pages, and the other collection scope remain untouched.
        """
        if not isinstance(tabs, list):
            return {"closed": 0, "kept": None}
        requested_route = self._solver_target_route(self.target_url)
        requested_scope = self._solver_target_scope(self.target_url)
        if not requested_route and not requested_scope:
            return {"closed": 0, "kept": None}
        challenge_tabs = []
        candidates = []
        for tab in tabs:
            if not isinstance(tab, dict) or tab.get("type") != "page":
                continue
            tab_url = str(tab.get("url") or "").strip()
            if not self._is_challenge_tab(tab):
                continue
            if self._is_login_url(tab_url):
                continue
            target_id = str(tab.get("id") or "").strip()
            if not target_id or not tab.get("webSocketDebuggerUrl"):
                continue
            candidate_scope = self._solver_target_scope(tab_url)
            if requested_scope:
                if candidate_scope != requested_scope:
                    continue
            elif self._solver_target_route(tab_url) != requested_route:
                continue
            challenge_tabs.append(tab)
            candidates.append(tab)
        exact_route_candidates = [
            tab
            for tab in candidates
            if requested_route and self._solver_target_route(tab.get("url")) == requested_route
        ]
        preserve_id = ""
        if exact_route_candidates:
            preserve_id = str(exact_route_candidates[0].get("id") or "").strip()
        if not preserve_id:
            preserve_id = str(self.target_id or "").strip()
        if not any(str(tab.get("id") or "").strip() == preserve_id for tab in candidates):
            preserve_id = str(candidates[0].get("id") or "").strip() if candidates else ""
        closed = 0
        for tab in challenge_tabs:
            target_id = str(tab.get("id") or "").strip()
            if target_id == preserve_id:
                continue
            if self._close_cdp_target(target_id):
                closed += 1
                self._opened_target_ids.discard(target_id)
        if closed:
            logger.info(
                f"[SOLVER] Compacted stale challenge targets for "
                f"{requested_scope or 'route ' + requested_route}: "
                f"kept={preserve_id} closed={closed}"
            )
        return {"closed": closed, "kept": preserve_id or None}

    def _normalize_target_url(self, value):
        if not value:
            return ""
        target_url = str(value).strip()
        if not target_url:
            return ""
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return target_url
        scheme = (parsed.scheme or "").lower()
        netloc = parsed.netloc
        if scheme in {"http", "https", "ws", "wss", "file"}:
            host = (parsed.hostname or "").lower()
            username = parsed.username or ""
            password = parsed.password or ""
            userinfo = username
            if password:
                userinfo = f"{userinfo}:{password}" if userinfo else f":{password}"
            if userinfo:
                userinfo = f"{userinfo}@"
            port = parsed.port
            default_port = 80 if scheme in {"http", "ws"} else 443
            normalized_netloc = f"{userinfo}{host}"
            if port and scheme != "file" and port != default_port:
                normalized_netloc = f"{normalized_netloc}:{port}"
            if scheme == "file" and parsed.netloc:
                normalized_netloc = parsed.netloc.lower()
            netloc = normalized_netloc
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        normalized_query = urlencode(sorted(query_pairs), doseq=True)
        path = parsed.path
        if scheme in {"http", "https", "ws", "wss"}:
            path = re.sub(r"/{2,}", "/", path)
        return urlunsplit((scheme, netloc, path, normalized_query, ""))

    def _solver_target_route(self, value):
        normalized = self._normalize_target_url(value)
        if not normalized:
            return ""
        try:
            parsed = urlsplit(normalized)
        except ValueError:
            return normalized
        path = parsed.path.replace("//", "/")
        if "/_____tmd_____/" in path:
            path = path.split("/_____tmd_____/", 1)[0]
        query_pairs = []
        is_taobao_list_route = bool(
            (parsed.hostname or "").lower() == "sf.taobao.com"
            and re.fullmatch(r"/list/[^/]+\.htm", path)
        )
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            if is_taobao_list_route and key not in SEED_IDENTITY_QUERY_KEYS:
                continue
            if key in {"__captcha_solver_bg", "track_id", "x5step", "x5secdata"}:
                continue
            query_pairs.append((key, item))
        query = urlencode(sorted(query_pairs), doseq=True)
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))

    def _solver_target_scope(self, value):
        """Classify auction URLs into the independent list/detail challenge scopes."""
        normalized = self._normalize_target_url(value)
        if not normalized:
            return ""
        try:
            parsed = urlsplit(normalized)
        except ValueError:
            return ""
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "/").replace("//", "/").lower()
        if host == "sf-item.taobao.com" or "/sf_item/" in path:
            return "detail"
        if host == "sf.taobao.com" and "/list/" in path:
            return "seed"
        if "/punish" in path and "/list/" in path:
            return "seed"
        return ""

    def _manual_challenge_matches_requested_target(self, value):
        if self._is_login_url(value):
            return True
        requested_route = self._solver_target_route(self.target_url)
        requested_scope = self._solver_target_scope(self.target_url)
        if not requested_route:
            return True
        challenge_route = self._solver_target_route(value)
        if not challenge_route:
            return False
        challenge_scope = self._solver_target_scope(value)
        if requested_scope and challenge_scope:
            return requested_scope == challenge_scope
        return challenge_route == requested_route

    def _rewrite_ws_url(self, ws_url):
        if not ws_url:
            return ws_url
        try:
            parsed_ws = urlsplit(ws_url)
            parsed_cdp = urlsplit(self.cdp_endpoint)
        except ValueError:
            return ws_url

        if parsed_ws.hostname not in {"127.0.0.1", "localhost"}:
            return ws_url

        target_netloc = parsed_cdp.netloc
        if not target_netloc:
            return ws_url
        return urlunsplit((parsed_ws.scheme, target_netloc, parsed_ws.path, parsed_ws.query, parsed_ws.fragment))

    def _target_requires_identity_before_navigation(self, target_url):
        try:
            parsed = urlsplit(str(target_url or ""))
        except ValueError:
            return False
        host = (parsed.hostname or "").lower()
        return parsed.scheme in {"http", "https"} and (
            host == "taobao.com" or host.endswith(".taobao.com")
        )

    def _prepare_opened_target_before_navigation(self, payload, target_url):
        if not isinstance(payload, dict):
            return False
        target_ws = str(payload.get("webSocketDebuggerUrl") or "").strip()
        if not target_ws:
            return False
        if not self._connect_to_target(target_ws, "new solver target"):
            return False
        navigation = self._send_cdp("Page.navigate", {"url": target_url})
        if navigation is None:
            logger.warning("[SOLVER] Identity-first target navigation failed.")
            return False
        payload["url"] = target_url
        self.current_target_url = target_url
        logger.info("[SOLVER] Opened target with browser identity installed before navigation.")
        return True


__all__ = ["CaptchaTargetMixin"]
