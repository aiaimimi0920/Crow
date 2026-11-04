"""Ephemeral input authority for an owned seed challenge; never business success."""

from dataclasses import dataclass

from .captcha_budget import SolveStopped
from .captcha_navigation_flow import NavigationTrace, _relation
from .captcha_navigation_receipt import NavigationReceipt, _receipt_is_current
from .captcha_verification import ready_target_matches

INPUT_BINDING_RESULTS = frozenset(
    {
        "accepted",
        "geometry_missing",
        "frame_unavailable",
        "receipt_unavailable",
        "trace_unavailable",
        "receipt_stale",
        "socket_changed",
        "page_not_ready",
        "document_changed",
        "document_url_mismatch",
        "binding_changed",
        "flow_inactive",
        "flow_frame_mismatch",
        "flow_requested_untrusted",
        "flow_request_invalid",
        "flow_origin_mismatch",
        "flow_redirect_mismatch",
        "flow_transition_unconfirmed",
        "flow_commit_mismatch",
        "flow_not_terminal",
    }
)


def root_frame(solver):
    if solver._stop_if_cancelled():
        raise SolveStopped(solver.last_failure_reason)
    result = solver._send_cdp("Page.getFrameTree")
    tree = result.get("frameTree") if isinstance(result, dict) else None
    frame = tree.get("frame") if isinstance(tree, dict) else None
    if solver._stop_if_cancelled():
        raise SolveStopped(solver.last_failure_reason)
    return frame if isinstance(frame, dict) and not frame.get("parentId") else None


def _document(frame):
    return tuple(frame.get(key) for key in ("id", "loaderId", "url")) if frame else None


def _flow_rejection(trace, receipt, frame):
    """Inspect every root transition, including unmatched requested-navigation."""
    previous = committed = requested = None
    if trace.state != "active":
        return "flow_inactive"
    if not frame or frame.get("id") != receipt.frame_id:
        return "flow_frame_mismatch"
    for row in trace.events:
        if row[1] != receipt.frame_id:
            continue
        if row[0] == "requested":
            if (
                requested
                or row[2] not in {"script", "meta"}
                or row[3] not in {"request", "queryless_challenge"}
            ):
                return "flow_requested_untrusted"
            requested = row[2:]
        elif row[0] == "request":
            _, _, loader, request_id, relation, redirect = row
            if (
                not loader
                or not request_id
                or relation not in {"request", "queryless_challenge"}
            ):
                return "flow_request_invalid"
            if previous is None:
                if (
                    relation != "request"
                    or redirect
                    or requested
                    or loader != receipt.loader_id
                ):
                    return "flow_origin_mismatch"
            elif redirect is not None:
                if requested or previous != (loader, request_id, redirect):
                    return "flow_redirect_mismatch"
            elif (
                not requested
                or requested[1] != relation
                or committed != (previous[0], previous[2])
            ):
                return "flow_transition_unconfirmed"
            previous = (loader, request_id, relation)
            requested = None
        elif row[0] == "commit":
            if (
                requested
                or not previous
                or (row[2], row[3]) != (previous[0], previous[2])
            ):
                return "flow_commit_mismatch"
            committed = row[2:]
    terminal = bool(
        not requested
        and previous
        and committed == (previous[0], "queryless_challenge")
        and frame.get("loaderId") == committed[0]
        and _relation(trace.target, frame.get("url")) == "queryless_challenge"
    )
    return None if terminal else "flow_not_terminal"


def _trusted_flow(trace, receipt, frame):
    return _flow_rejection(trace, receipt, frame) is None


def _binding_denied(solver, reason):
    solver._last_challenge_binding_result = reason
    return None


@dataclass(frozen=True, repr=False)
class ChallengeInputBinding:
    receipt: NavigationReceipt
    trace: NavigationTrace
    document: tuple
    event_count: int


def challenge_input_binding(solver, summary, *, before=None):
    """Use raw document identity plus the full private event chain, not log enums."""
    receipt = getattr(solver, "_navigation_receipt", None)
    trace = getattr(solver, "_navigation_trace", None)
    if not isinstance(receipt, NavigationReceipt):
        return _binding_denied(solver, "receipt_unavailable")
    if not isinstance(trace, NavigationTrace):
        return _binding_denied(solver, "trace_unavailable")
    if (
        not _receipt_is_current(solver, receipt)
        or solver._solver_target_scope(solver.target_url) != "seed"
    ):
        return _binding_denied(solver, "receipt_stale")
    if (
        solver.ws is not trace.socket
        or getattr(trace.socket, "connected", None) is not True
    ):
        return _binding_denied(solver, "socket_changed")
    if (
        summary.get("probeFailed")
        or summary.get("loginRequired")
        or summary.get("authenticatedPage")
        or summary.get("readyState") not in {"interactive", "complete"}
        or not (summary.get("hasSlider") or summary.get("hasChallengeWidget"))
    ):
        return _binding_denied(solver, "page_not_ready")
    frame = root_frame(solver)
    if not frame:
        return _binding_denied(solver, "frame_unavailable")
    if before is not None and _document(before) != _document(frame):
        return _binding_denied(solver, "document_changed")
    if frame.get("url") != summary.get("href"):
        return _binding_denied(solver, "document_url_mismatch")
    rejection = _flow_rejection(trace, receipt, frame)
    if rejection:
        return _binding_denied(solver, rejection)
    if (
        solver._navigation_receipt is not receipt
        or solver.ws is not trace.socket
        or not _receipt_is_current(solver, receipt)
    ):
        return _binding_denied(solver, "binding_changed")
    solver._last_challenge_binding_result = "accepted"
    return ChallengeInputBinding(receipt, trace, _document(frame), len(trace.events))


def challenge_binding_is_current(solver, binding):
    if not isinstance(binding, ChallengeInputBinding):
        return False
    if (
        getattr(solver, "_navigation_receipt", None) is not binding.receipt
        or getattr(solver, "_navigation_trace", None) is not binding.trace
        or solver.ws is not binding.trace.socket
        or getattr(binding.trace.socket, "connected", None) is not True
        or not _receipt_is_current(solver, binding.receipt)
    ):
        return False
    frame = root_frame(solver)
    return (
        _document(frame) == binding.document
        and getattr(solver, "_navigation_receipt", None) is binding.receipt
        and solver.ws is binding.trace.socket
        and getattr(binding.trace.socket, "connected", None) is True
        and _receipt_is_current(solver, binding.receipt)
        and len(binding.trace.events) == binding.event_count
        and _trusted_flow(binding.trace, binding.receipt, frame)
    )


def input_target_matches(solver, summary):
    return (
        ready_target_matches(summary, solver.target_url)
        or challenge_input_binding(solver, summary) is not None
    )
