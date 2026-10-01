"""Closed configuration contract. No arbitrary environment, paths or commands."""
from copy import deepcopy
from urllib.parse import urlsplit

from .collection_engine_restart import RestartError

PREFIX = "/api/collection/settings"
ROLES = {PREFIX: "operator", PREFIX + "/apply": "operator",
         PREFIX + "/poll": "agent", PREFIX + "/result": "agent"}
NUMBERS = {
    "workers": {"links": (1, 2), "details": (1, 8), "analysis": (1, 8)},
    "intervals": {"links": (1, 3600), "details": (1, 3600), "analysis": (1, 3600),
                  "links_idle": (1, 3600), "details_idle": (1, 3600), "analysis_idle": (1, 3600),
                  "success_delay": (0, 300), "failure_delay": (1, 3600)},
    "retries": {"detail_item_attempts": (1, 20), "analysis_item_attempts": (1, 20), "detail_batch_attempts": (1, 200),
                "analysis_batch_attempts": (1, 200), "ai_attempts": (0, 10)},
    "ai": {"timeout_seconds": (5, 600)},
}


def reject(message):
    raise RestartError(message, 400)


def validate(value):
    if not isinstance(value, dict) or set(value) != set(NUMBERS):
        reject("Invalid settings groups")
    result = deepcopy(value)
    for group, numbers in NUMBERS.items():
        expected = set(numbers) | ({"base_url", "model"} if group == "ai" else set())
        if not isinstance(result[group], dict) or set(result[group]) != expected:
            reject("Invalid settings fields: " + group)
        for name, (minimum, maximum) in numbers.items():
            number = result[group][name]
            allowed = (int, float) if name in {"success_delay", "failure_delay"} else (int,)
            if type(number) not in allowed or not minimum <= number <= maximum:
                reject("Invalid numeric setting: " + group + "." + name)
    if sum(result["workers"].values()) > 16:
        reject("Total worker count must not exceed 16")
    ai = result["ai"]
    if not isinstance(ai["base_url"], str) or not isinstance(ai["model"], str):
        reject("AI address and model must be strings")
    try:
        url = urlsplit(ai["base_url"])
        port = url.port
    except ValueError:
        reject("Invalid AI address")
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or len(ai["base_url"]) > 1024
            or any(ord(char) < 33 for char in ai["base_url"]) or port == 0):
        reject("Use an HTTP(S) AI base URL without credentials or query parameters")
    model = ai["model"].strip()
    if not model or len(model) > 200 or any(char.isspace() for char in model):
        reject("Invalid AI model route")
    from .llm_analysis_policy import require_non_gpt_analysis_model
    try:
        require_non_gpt_analysis_model(model, setting="ai.model")
    except ValueError:
        reject("Current collection policy requires a non-GPT analysis model")
    ai.update(base_url=ai["base_url"].rstrip("/"), model=model)
    return result


def validate_key(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not 8 <= len(value) <= 2048 or any(char.isspace() for char in value):
        reject("Invalid AI key; leave blank to retain the current key")
    return value


def environment_changes(config, stage):
    """Legacy key mapping retained for callers; scoped writers synchronize aliases."""
    config = validate(config)
    intervals, retries, ai = config["intervals"], config["retries"], config["ai"]
    if stage == "links":
        return {"FAPAI_SEED_LOOP_INTERVAL_SECONDS": str(intervals[stage + "_idle"]),
                "FAPAI_SEED_ACTIVE_LOOP_INTERVAL_SECONDS": str(intervals[stage])}
    result = {
        "FAPAI_DETAIL_LOOP_INTERVAL_SECONDS": str(intervals[stage + "_idle"]),
        "FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS": str(intervals[stage]),
        "FAPAI_DETAIL_ITEM_MAX_ATTEMPTS": str(retries["analysis_item_attempts" if stage == "analysis" else "detail_item_attempts"]),
        "FAPAI_DETAIL_MAX_ATTEMPTS": str(retries["analysis_batch_attempts" if stage == "analysis" else "detail_batch_attempts"]),
    }
    if stage == "details":
        result.update(FAPAI_DETAIL_SUCCESS_DELAY_SECONDS=str(intervals["success_delay"]),
                      FAPAI_DETAIL_FAILURE_DELAY_SECONDS=str(intervals["failure_delay"]))
    if stage == "analysis":
        result.update(OPENAI_BASE_URL=ai["base_url"], OPENAI_MODEL=ai["model"],
                      OPENAI_MODEL_CANDIDATES=ai["model"],
                      OPENAI_TIMEOUT_SECONDS=str(ai["timeout_seconds"]),
                      OPENAI_MAX_RETRIES=str(retries["ai_attempts"]))
    return result
