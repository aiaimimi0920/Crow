"""Navigation ACK validation and bounded, non-authorizing document diagnostics."""

from dataclasses import dataclass

from .captcha_budget import SolveStopped
from .captcha_navigation_flow import FLOW_ENUMS, navigation_flow_fields
from .collection.adapters.taobao_auth_target import (
    canonical_auth_target,
    same_auth_target,
)

NAVIGATION_ENUMS = {
    "navigation_probe": {"ok", "unavailable", "limited", "target_changed"},
    "navigation_frame": {"match", "different", "missing", "unavailable", "not_read"},
    "navigation_loader": {"match", "different", "missing", "unavailable", "not_read"},
    "navigation_url": {"match", "different", "invalid", "unavailable", "not_read"},
}


def accepted_navigation_reply(value):
    """A frame ID alone does not override an explicit failure or a download."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("frameId"), str)
        and bool(value["frameId"].strip())
        and "errorText" not in value
        and ("isDownload" not in value or value["isDownload"] is False)
        and (
            "loaderId" not in value
            or isinstance(value["loaderId"], str)
            and bool(value["loaderId"].strip())
        )
    )


@dataclass(frozen=True, repr=False)
class NavigationReceipt:
    """Private per-instance correlation values; never serialize or log them."""

    target_id: str
    target_url: str
    frame_id: str
    loader_id: str | None


def safe_navigation_fields(value):
    if not isinstance(value, dict):
        return {}
    fields = {
        key: item
        if isinstance(item := value.get(key), str) and item in allowed
        else "unknown"
        for key, allowed in NAVIGATION_ENUMS.items()
    }
    for key, allowed in FLOW_ENUMS.items():
        if key in value:
            fields[key] = (
                value[key]
                if isinstance(value[key], str) and value[key] in allowed
                else "unknown"
            )
    return fields


def _relation(expected, current):
    if not isinstance(expected, str) or not expected:
        return "missing"
    if not isinstance(current, str) or not current:
        return "missing"
    return "match" if current == expected else "different"


def _url_relation(first, second):
    for scope in ("seed", "detail"):
        try:
            a = canonical_auth_target(scope, first)
            b = canonical_auth_target(scope, second)
        except (ValueError, TypeError, AttributeError):
            continue
        return "match" if same_auth_target(scope, a, b) else "different"
    return "invalid"


def _receipt_is_current(solver, receipt):
    try:
        return (
            receipt.target_id == solver.target_id
            and receipt.target_id in solver._opened_target_ids
            and receipt.target_url == solver._normalize_target_url(solver.target_url)
        )
    except (ValueError, TypeError, AttributeError):
        return False


def navigation_binding_fields(solver, summary):
    """Compare a fresh root-frame snapshot; never authorize input or business auth.

    At most three extra read-only commands per receipt, inside the existing solve
    budget. No cached snapshot is reported as a fresh document comparison.
    """
    receipt = getattr(solver, "_navigation_receipt", None)
    if not isinstance(receipt, NavigationReceipt):
        return {}
    fields = {key: "not_read" for key in NAVIGATION_ENUMS}
    fields["navigation_probe"] = "target_changed"
    if not _receipt_is_current(solver, receipt):
        return fields
    if solver._stop_if_cancelled():
        raise SolveStopped(solver.last_failure_reason)
    reads = getattr(solver, "_navigation_binding_reads", 0)
    if reads >= 3:
        fields["navigation_probe"] = "limited"
        return fields
    solver._navigation_binding_reads = reads + 1
    try:
        result = solver._send_cdp("Page.getFrameTree")
    except SolveStopped:
        raise
    except Exception:  # noqa: BLE001 -- diagnostics cannot replace the existing outcome
        result = None
    if solver._stop_if_cancelled():
        raise SolveStopped(solver.last_failure_reason)
    if solver._navigation_receipt is not receipt or not _receipt_is_current(
        solver, receipt
    ):
        return fields
    tree = result.get("frameTree") if isinstance(result, dict) else None
    frame = tree.get("frame") if isinstance(tree, dict) else None
    if not isinstance(frame, dict) or frame.get("parentId"):
        return {key: "unavailable" for key in NAVIGATION_ENUMS}
    return {
        "navigation_probe": "ok",
        "navigation_frame": _relation(receipt.frame_id, frame.get("id")),
        "navigation_loader": _relation(receipt.loader_id, frame.get("loaderId")),
        "navigation_url": _url_relation(
            frame.get("url"), summary.get("href") if isinstance(summary, dict) else None
        ),
        **navigation_flow_fields(solver, frame),
    }
