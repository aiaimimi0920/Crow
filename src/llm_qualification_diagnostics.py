"""Safe HTTP failure facts, before pool failover hides the original status."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re

logger = logging.getLogger(__name__)


def report_request_failure(model: str, *, probe: bool, error: Exception) -> None:
    """Best effort only: never log exception text, URLs, headers or response bodies."""
    try:
        # Resolve this identifier against the existing pool/catalog offline.
        # Even a credential accidentally supplied as a model must not be logged.
        model_id = "sha256:" + hashlib.sha256(model.encode("utf-8")).hexdigest()
        status = getattr(error, "status_code", None)
        if type(status) is not int or not 100 <= status <= 599:
            status = None
        retry_after = getattr(error, "retry_after_seconds", None)
        if (
            type(retry_after) not in (int, float)
            or not math.isfinite(retry_after)
            or not 0 <= retry_after <= 31_536_000
        ):
            retry_after = None
        error_type = type(error).__name__
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", error_type):
            error_type = "Exception"
        event = {
            "kind": "analysis_model_request_failure",
            "model": model_id,
            "phase": "qualification" if probe else "business",
            "status_code": status,
            "retry_after_seconds": retry_after,
            "error_type": error_type,
        }
        logger.warning("%s", json.dumps(event, ensure_ascii=False))
    except Exception:  # noqa: BLE001 -- a broken diagnostic sink must preserve the original request failure
        return
