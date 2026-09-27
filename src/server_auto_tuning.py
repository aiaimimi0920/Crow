from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def auto_tuner_thread() -> None:
    """
    Background thread for automatic concurrency tuning.
    Runs every 5 minutes, analyzes error rates, and adjusts ModelSelector limits.
    """
    from src.llm_model_selector import get_model_selector

    model_selector = get_model_selector()

    TUNING_INTERVAL = 5 * 60  # 5 minutes
    MIN_REQUESTS = 20
    ERROR_RATE_LOW = 1.0  # Below this: increase
    ERROR_RATE_HIGH = 5.0  # Above this: decrease
    MAX_LIMIT = 20
    MIN_LIMIT = 3
    STEP_SIZE = 2
    STABLE_ROUNDS = 2

    stable_count = {m["name"]: 0 for m in model_selector.pool}
    is_stable = False

    logger.info("[AUTO-TUNER] Started (5-minute intervals)")

    while True:
        time.sleep(TUNING_INTERVAL)

        if is_stable:
            # Already stable, just monitor
            continue

        try:
            stats = model_selector.get_stats()

            logger.info("[AUTO-TUNER] Analysis @ %s", time.strftime("%H:%M:%S"))

            for name, s in stats.items():
                current_limit = model_selector.limits.get(name, 5)
                total = s["success"] + s["error"]

                if total < MIN_REQUESTS:
                    logger.info(
                        "  [%s] Requests %s < %s, skipping", name, total, MIN_REQUESTS
                    )
                    continue

                error_rate = (s["concurrency_error"] / total * 100) if total > 0 else 0

                if error_rate < ERROR_RATE_LOW and current_limit < MAX_LIMIT:
                    new_limit = min(current_limit + STEP_SIZE, MAX_LIMIT)
                    logger.info(
                        "  [%s] Error %.1f%% < %s%%; %s -> %s",
                        name,
                        error_rate,
                        ERROR_RATE_LOW,
                        current_limit,
                        new_limit,
                    )
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                elif error_rate > ERROR_RATE_HIGH and current_limit > MIN_LIMIT:
                    new_limit = max(current_limit - STEP_SIZE, MIN_LIMIT)
                    logger.info(
                        "  [%s] Error %.1f%% > %s%%; %s -> %s",
                        name,
                        error_rate,
                        ERROR_RATE_HIGH,
                        current_limit,
                        new_limit,
                    )
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                else:
                    logger.info(
                        "  [%s] Error %.1f%% OK, keeping %s",
                        name,
                        error_rate,
                        current_limit,
                    )
                    stable_count[name] += 1

            # Reset stats for next round
            with model_selector.stats_lock:
                for name in model_selector.stats:
                    model_selector.stats[name] = {
                        "success": 0,
                        "error": 0,
                        "concurrency_error": 0,
                        "active": model_selector.stats[name]["active"],
                    }

            # Check stability
            if min(stable_count.values()) >= STABLE_ROUNDS:
                is_stable = True
                logger.info(
                    "[AUTO-TUNER] Stable; final config: %s", model_selector.limits
                )

        except Exception:
            logger.exception("[AUTO-TUNER] Error")


__all__ = ["auto_tuner_thread"]
