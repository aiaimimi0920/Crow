"""Bounded native seed-navigation diagnostics, never input or auth authority."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .captcha_budget import SolveStopped
from .collection.adapters.taobao_auth_target import (
    canonical_auth_target,
    same_auth_target,
)

FLOW_ENUMS = {
    "navigation_capture": {"active", "unavailable", "limited", "disconnected"},
    "navigation_origin": {
        "request",
        "queryless_challenge",
        "different",
        "invalid",
        "not_seen",
    },
    "navigation_transition": {
        "none",
        "http_redirect",
        "script",
        "meta",
        "other",
        "mixed",
    },
    "navigation_commit": {
        "request",
        "queryless_challenge",
        "different",
        "invalid",
        "not_seen",
    },
    "navigation_flow_loader": {"match", "different", "missing", "not_read"},
    "navigation_flow_pending": {"yes", "no", "unknown"},
}
EVENTS = {
    "Network.requestWillBeSent",
    "Page.frameNavigated",
    "Page.frameRequestedNavigation",
}


def _identity(value):
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def _relation(target, value):
    if not isinstance(value, str) or len(value) > 8192:
        return "invalid"
    try:
        current = canonical_auth_target("seed", value)
        if same_auth_target("seed", target, current):
            return "request"
        expected, parsed = urlsplit(target), urlsplit(current)
        if (
            "/_____tmd_____/" in urlsplit(value).path
            and (expected.scheme, expected.netloc, expected.path)
            == (parsed.scheme, parsed.netloc, parsed.path)
            and not parsed.query
        ):
            return "queryless_challenge"
        return "different"
    except (ValueError, TypeError, AttributeError):
        return "invalid"


@dataclass(repr=False, eq=False)
class NavigationTrace:
    target: str
    socket: object
    state: str = "unavailable"
    events: list = field(default_factory=list)

    def observe(self, message):
        if self.state != "active" or message.get("method") not in EVENTS:
            return
        params = message.get("params")
        if not isinstance(params, dict):
            self.state = "unavailable"
            return
        method = message["method"]
        if method == "Network.requestWillBeSent" and params.get("type") != "Document":
            return
        if len(self.events) >= 64:
            self.state = "limited"
            return
        if method == "Page.frameNavigated":
            frame = params.get("frame")
            if not isinstance(frame, dict):
                self.state = "unavailable"
                return
            if frame.get("parentId"):
                return
            row = (
                "commit",
                _identity(frame.get("id")),
                _identity(frame.get("loaderId")),
                _relation(self.target, frame.get("url")),
            )
        elif method == "Page.frameRequestedNavigation":
            reason = {"scriptInitiated": "script", "metaTagRefresh": "meta"}.get(
                params.get("reason"), "other"
            )
            row = (
                "requested",
                _identity(params.get("frameId")),
                reason,
                _relation(self.target, params.get("url")),
            )
        else:
            request = params.get("request")
            redirect = params.get("redirectResponse")
            if not isinstance(request, dict) or (
                redirect is not None and not isinstance(redirect, dict)
            ):
                self.state = "unavailable"
                return
            row = (
                "request",
                _identity(params.get("frameId")),
                _identity(params.get("loaderId")),
                _identity(params.get("requestId")),
                _relation(self.target, request.get("url")),
                _relation(self.target, redirect.get("url")) if redirect else None,
            )
        self.events.append(row)

    def snapshot(self, frame):
        root = frame.get("id")
        origin = commit = "not_seen"
        previous = pending = committed_loader = None
        transitions = set()
        requested = None
        for row in self.events:
            if row[1] != root:
                continue
            if row[0] == "requested":
                requested = row[2:]
            elif row[0] == "commit":
                committed_loader, commit = row[2:]
            else:
                _, _, loader, request_id, relation, redirect = row
                if previous is None:
                    origin = relation
                else:
                    kind = "other"
                    if redirect is not None and previous == (
                        loader,
                        request_id,
                        redirect,
                    ):
                        kind = "http_redirect"
                    elif requested and requested[1] == relation:
                        kind = requested[0]
                    transitions.add(kind)
                previous = (loader, request_id, relation)
                pending = loader
                requested = None
        current = _identity(frame.get("loaderId"))
        return {
            "navigation_capture": self.state,
            "navigation_origin": origin,
            "navigation_transition": "none"
            if not transitions
            else next(iter(transitions))
            if len(transitions) == 1
            else "mixed",
            "navigation_commit": commit,
            "navigation_flow_loader": "missing"
            if not committed_loader or not current
            else "match"
            if committed_loader == current
            else "different",
            "navigation_flow_pending": "unknown"
            if not pending
            else "no"
            if pending == committed_loader
            else "yes",
        }


def begin_navigation_trace(solver, payload, target):
    solver._navigation_trace = None
    if (
        solver._solver_target_scope(target) != "seed"
        or payload.get("id") != solver.target_id
        or solver.target_id not in solver._opened_target_ids
        or getattr(solver.ws, "connected", None) is not True
    ):
        return
    try:
        canonical = canonical_auth_target("seed", target)
    except (ValueError, TypeError, AttributeError):
        return
    trace = NavigationTrace(canonical, solver.ws)
    solver._navigation_trace = trace
    for method, params in (
        ("Page.enable", None),
        (
            "Network.enable",
            {
                "maxTotalBufferSize": 65536,
                "maxResourceBufferSize": 16384,
                "maxPostDataSize": 0,
            },
        ),
    ):
        try:
            if solver._send_cdp(method, params) is None:
                return
        except SolveStopped:
            raise
        except Exception:  # noqa: BLE001 -- optional telemetry cannot replace navigation
            return
    trace.state = "active"


def observe_navigation_event(solver, sock, message):
    trace = getattr(solver, "_navigation_trace", None)
    if isinstance(trace, NavigationTrace) and trace.socket is sock:
        try:
            trace.observe(message)
        except (ValueError, TypeError, AttributeError, KeyError):
            trace.state = "unavailable"


def invalidate_navigation_trace(solver, sock):
    trace = getattr(solver, "_navigation_trace", None)
    if isinstance(trace, NavigationTrace) and trace.socket is sock:
        trace.state = "unavailable"


def navigation_flow_fields(solver, frame):
    trace = getattr(solver, "_navigation_trace", None)
    if not isinstance(trace, NavigationTrace):
        return {}
    fields = trace.snapshot(frame)
    if (
        solver.ws is not trace.socket
        or getattr(trace.socket, "connected", None) is not True
    ):
        fields["navigation_capture"] = "disconnected"
    return fields
