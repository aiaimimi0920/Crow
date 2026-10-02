"""Poll confirmed seed recovery instead of sleeping through a cleared challenge."""

import time

from tools import worker_lifecycle
from tools.internal_api_http import fetch_json
from tools.seed_collector_context import SeedCollectorConfig


def wait_after_seed_run(
    config: SeedCollectorConfig, results: list[dict], seconds: float
) -> None:
    challenge_wait = any(
        item.get("decision") == "seed_collection_paused"
        or item.get("reason") == "list_challenge_page"
        or bool((item.get("auth_probe") or {}).get("attempted"))
        for item in results
    )
    if (
        not config.api_base_url
        or not challenge_wait
        or seconds <= 30
        or any(item.get("decision") == "seed_page_collected" for item in results)
    ):
        worker_lifecycle.wait(seconds)
        return

    deadline = time.monotonic() + seconds
    while worker_lifecycle.checkpoint("seed_auth_backoff"):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        worker_lifecycle.wait(min(remaining, 30))
        if not worker_lifecycle.checkpoint("seed_auth_backoff"):
            return
        try:
            status = fetch_json(config.api_base_url.rstrip("/") + "/status", timeout=5)
        except (OSError, ValueError, TimeoutError):
            continue
        if not isinstance(status, dict):
            continue
        scopes = status.get("collection_scopes")
        seed = scopes.get("seed") if isinstance(scopes, dict) else None
        detail = scopes.get("detail") if isinstance(scopes, dict) else None
        if status.get("paused") is not False and not (
            status.get("paused") is True
            and isinstance(detail, dict)
            and detail.get("paused") is True
        ):
            continue
        if (
            isinstance(seed, dict)
            and seed.get("paused") is False
            and seed.get("manual_required") is False
            and not seed.get("challenge_id")
        ):
            return
