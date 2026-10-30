"""Shared allowlist for target-binding telemetry and persisted event readback."""

BINDING_ENUMS = {
    "stage": frozenset({"preflight", "post_drag", "retry_preclick"}),
    "binding": frozenset(
        {
            "match",
            "request_invalid",
            "current_invalid",
            "scope_changed",
            "path_changed",
            "query_changed",
        }
    ),
    **dict.fromkeys(
        ("location_code", "st_param", "auction_start_seg", "page"),
        frozenset(
            {
                "not_compared",
                "both_absent",
                "equal",
                "current_missing",
                "request_missing",
                "different",
            }
        ),
    ),
    "navigation_probe": frozenset({"ok", "unavailable", "limited", "target_changed"}),
    "navigation_frame": frozenset(
        {"match", "different", "missing", "unavailable", "not_read"}
    ),
    "navigation_loader": frozenset(
        {"match", "different", "missing", "unavailable", "not_read"}
    ),
    "navigation_url": frozenset(
        {"match", "different", "invalid", "unavailable", "not_read"}
    ),
    "navigation_capture": frozenset(
        {"active", "unavailable", "limited", "disconnected"}
    ),
    "navigation_origin": frozenset(
        {"request", "queryless_challenge", "different", "invalid", "not_seen"}
    ),
    "navigation_transition": frozenset(
        {"none", "http_redirect", "script", "meta", "other", "mixed"}
    ),
    "navigation_commit": frozenset(
        {"request", "queryless_challenge", "different", "invalid", "not_seen"}
    ),
    "navigation_flow_loader": frozenset({"match", "different", "missing", "not_read"}),
    "navigation_flow_pending": frozenset({"yes", "no", "unknown"}),
}


def binding_evidence(event):
    """Revalidate even previously projected events; never copy arbitrary fields."""
    evidence = {}
    for key, allowed in BINDING_ENUMS.items():
        if key in event:
            value = event[key]
            evidence[key] = (
                value if isinstance(value, str) and value in allowed else "unknown"
            )
    return evidence
