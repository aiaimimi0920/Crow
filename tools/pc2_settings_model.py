"""Pure Compose plan generation from operator-provisioned, resolved runtime input."""
from copy import deepcopy
import re

from src.collection_settings_schema import environment_changes, validate
from src.project_environment import getenv, set_env

STAGES = {"links": "seed", "details": "detail", "analysis": "analysis"}
WORKER = re.compile(r"pc2-(seed|detail|analysis)-([1-8])\Z")


def _read(environment, key, default=None):
    return getenv(key, default, reader=environment.get)


def workers(model):
    if any(name != "pc2-browser-solver" and not WORKER.fullmatch(name) for name in model["services"]):
        raise ValueError("Compose contains unsupported services; refuse unbounded reconciliation")
    return {name: value for name, value in model["services"].items() if WORKER.fullmatch(name)}


def inventory(model):
    services = workers(model)
    groups = {stage: [value for name, value in services.items() if name.startswith("pc2-" + role + "-")]
              for stage, role in STAGES.items()}
    if any(not group for group in groups.values()):
        raise ValueError("Each collection stage requires a provisioned template")
    for stage, role in STAGES.items():
        if any(f"pc2-{role}-{index}" not in services for index in range(1, len(groups[stage]) + 1)):
            raise ValueError("Worker identities must be contiguous within each stage")
    env = {stage: model["services"]["pc2-" + role + "-1"]["environment"] for stage, role in STAGES.items()}
    detail, ai = env["details"], env["analysis"]
    config = {
        "workers": {stage: len(group) for stage, group in groups.items()},
        "intervals": {
            "links": int(_read(env["links"], "CROW_SEED_ACTIVE_LOOP_INTERVAL_SECONDS", _read(env["links"], "CROW_SEED_LOOP_INTERVAL_SECONDS", 1800))),
            "details": int(_read(detail, "CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS", _read(detail, "CROW_DETAIL_LOOP_INTERVAL_SECONDS", 900))),
            "analysis": int(_read(ai, "CROW_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS", _read(ai, "CROW_DETAIL_LOOP_INTERVAL_SECONDS", 900))),
            "links_idle": int(_read(env["links"], "CROW_SEED_LOOP_INTERVAL_SECONDS", 1800)),
            "details_idle": int(_read(detail, "CROW_DETAIL_LOOP_INTERVAL_SECONDS", 900)),
            "analysis_idle": int(_read(ai, "CROW_DETAIL_LOOP_INTERVAL_SECONDS", 900)),
            "success_delay": float(_read(detail, "CROW_DETAIL_SUCCESS_DELAY_SECONDS", 6)),
            "failure_delay": float(_read(detail, "CROW_DETAIL_FAILURE_DELAY_SECONDS", 15)),
        },
        "retries": {"detail_item_attempts": int(_read(detail, "CROW_DETAIL_ITEM_MAX_ATTEMPTS", 3)),
                    "analysis_item_attempts": int(_read(ai, "CROW_DETAIL_ITEM_MAX_ATTEMPTS", 3)),
                    "detail_batch_attempts": int(_read(detail, "CROW_DETAIL_MAX_ATTEMPTS", 20)),
                    "analysis_batch_attempts": int(_read(ai, "CROW_DETAIL_MAX_ATTEMPTS", 20)),
                    "ai_attempts": int(_read(ai, "OPENAI_MAX_RETRIES", 3))},
        "ai": {"base_url": _read(ai, "OPENAI_BASE_URL", ""), "model": _read(ai, "OPENAI_MODEL", ""),
               "timeout_seconds": int(float(_read(ai, "OPENAI_TIMEOUT_SECONDS", 180)))},
    }
    config = validate(config)
    for stage, group in groups.items():
        keys = set(environment_changes(config, stage))
        if stage == "analysis":
            keys.add("OPENAI_API_KEY")
        if any(any(_read(service["environment"], key) != _read(env[stage], key) for key in keys) for service in group):
            raise ValueError("Workers in one stage must share the exposed settings")
    return {"effective": config, "api_key_configured": bool(_read(ai, "OPENAI_API_KEY"))}


def render(model, config, api_key=None):
    config = validate(config)
    previous = inventory(model)["effective"]
    result = deepcopy(model)
    templates = {stage: deepcopy(model["services"]["pc2-" + role + "-1"]) for stage, role in STAGES.items()}
    for name in workers(result):
        del result["services"][name]
    for stage, role in STAGES.items():
        for index in range(1, config["workers"][stage] + 1):
            name = f"pc2-{role}-{index}"
            service = deepcopy(model["services"].get(name, templates[stage]))
            service["container_name"] = "fapaifang-" + name
            env = service["environment"]
            old_values = environment_changes(previous, stage)
            for key, value in environment_changes(config, stage).items():
                if old_values[key] != value:
                    set_env(key, value, environ=env)
            if name not in model["services"]:
                set_env("CROW_SEED_WORKER_ID" if stage == "links" else "CROW_DETAIL_WORKER_ID", f"{role}-{index}", environ=env)
                set_env("CROW_OUTPUT_DIR", _read(templates[stage]["environment"], "CROW_OUTPUT_DIR") + f"_{index}", environ=env)
            if stage == "analysis" and api_key:
                env["OPENAI_API_KEY"] = api_key
            result["services"][name] = service
    return result


def literal_compose(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [literal_compose(item) for item in value]
    if isinstance(value, dict):
        return {key: literal_compose(item) for key, item in value.items()}
    return value
