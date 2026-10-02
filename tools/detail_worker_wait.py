"""Wake a challenge backoff only after the API confirms authentication resumed."""

import time

from tools import worker_lifecycle
from tools.detail_worker_context import DetailWorkerConfig
from tools.internal_api_http import fetch_json


def wait_after_detail_batch(
    config: DetailWorkerConfig, result: dict, seconds: float
) -> None:
    challenge_wait = any(
        isinstance(item, dict)
        and (
            item.get("decision") == "detail_collection_paused"
            or item.get("reason")
            in {"detail_challenge_page", "detail_stale_challenge_ignored"}
        )
        for item in result.get("results") or []
    )
    if (
        config.analysis_only
        or not config.api_base_url
        or not challenge_wait
        or seconds <= 30
    ):
        worker_lifecycle.wait(seconds)
        return

    deadline = time.monotonic() + seconds
    while worker_lifecycle.checkpoint("detail_auth_backoff"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        worker_lifecycle.wait(min(remaining, 30))
        if not worker_lifecycle.checkpoint("detail_auth_backoff"):
            return
        try:
            status = fetch_json(config.api_base_url.rstrip("/") + "/status", timeout=5)
        except (OSError, ValueError, TimeoutError):
            continue
        if not isinstance(status, dict):
            continue
        scopes = status.get("collection_scopes")
        detail = scopes.get("detail") if isinstance(scopes, dict) else None
        seed = scopes.get("seed") if isinstance(scopes, dict) else None
        # The aggregate pause includes seed-only challenges. A confirmed clear
        # detail scope must not inherit another stage's 15-minute backoff.
        if status.get("paused") is not False and not (
            status.get("paused") is True
            and isinstance(seed, dict)
            and seed.get("paused") is True
        ):
            continue
        if (
            isinstance(detail, dict)
            and detail.get("paused") is False
            and detail.get("manual_required") is False
            and not detail.get("challenge_id")
        ):
            return
