"""Allowlisted pointer and trusted-input receipt projection; no page payloads."""

POINTER_PHASES = {
    "input_receipt",
    "input_receipt_unavailable",
    "slider_geometry",
    "drag_distance",
    "pointer_failure",
    "pointer_hit",
    "cursor_position",
}


def pointer_evidence(event):
    evidence = {}
    if event["phase"] in {"input_receipt", "input_receipt_unavailable"}:
        for key in (
            "backend_completed",
            "press_seen",
            "press_on_target",
            "release_seen",
            "document_current",
        ):
            if type(event.get(key)) is bool:
                evidence[key] = event[key]
        value = event.get("pressed_moves")
        if type(value) is int and 0 <= value <= 10000:
            evidence["pressed_moves"] = value
        return evidence
    if event["phase"] == "pointer_failure":
        for key, allowed in (
            (
                "reason",
                {
                    "target_unavailable",
                    "target_invalid",
                    "target_changed",
                    "pointer_unobserved",
                    "pointer_changed",
                    "pointer_missed",
                },
            ),
            (
                "check",
                {
                    "target",
                    "native_focus",
                    "snapshot",
                    "event_buttons",
                    "event_serial",
                    "event_age",
                    "open_native_focus",
                    "open_snapshot",
                    "open_binding",
                    "binding_missing",
                    "binding_document",
                    "binding_expired",
                    "binding_changed",
                    "node_unavailable",
                    "frame_unavailable",
                    "track_unavailable",
                },
            ),
        ):
            value = event.get(key)
            evidence[key] = (
                value if isinstance(value, str) and value in allowed else "unknown"
            )
    for key in ("delta", "corrections", "track_width", "slider_width"):
        value = event.get(key)
        if type(value) in (int, float) and 0 <= value <= 10000:
            evidence[key] = value
    return evidence
