"""Separate durable capture acknowledgement from executor admission."""


def submission_receipt(state):
    # `queued` is the historical intake ACK, not evidence of model execution.
    if state is None:
        state = "unknown"
    if state not in {
        "accepted",
        "duplicate",
        "not_ready",
        "error",
        "blocked_status",
        "unknown",
    }:
        raise ValueError(f"Unexpected capture submission state: {state!r}")
    result = {
        "status": "queued",
        "capture_saved": True,
        "submission_state": state,
        "processing_queued": state in {"accepted", "duplicate"},
    }
    if not result["processing_queued"]:
        result["retry_after"] = 30
    return result
