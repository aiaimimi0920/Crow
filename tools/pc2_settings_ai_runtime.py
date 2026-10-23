"""AI-environment-only exact-ID replacement, with stopped containers retained."""

import os
import subprocess
import uuid
from copy import deepcopy

from src.collection_settings_schema import environment_changes
from src.project_environment import set_env

from .pc2_docker_api import DockerAPI, clone_payload
from .pc2_settings_model import inventory, workers


def ai_only(before, after, changed, removed):
    if removed or not changed or set(workers(before)) != set(workers(after)):
        return False
    allowed = {"OPENAI_API_KEY": ""}
    for key in environment_changes(inventory(after)["effective"], "analysis"):
        if key.startswith("OPENAI_") or key == "CROW_ANALYSIS_ALLOW_GPT":
            set_env(key, "", environ=allowed)
    for name in changed:
        if not name.startswith("pc2-analysis-"):
            return False
        old, new = deepcopy(before["services"][name]), deepcopy(after["services"][name])
        left, right = old.pop("environment"), new.pop("environment")
        if old != new or any(
            left.get(key) != right.get(key)
            for key in set(left) | set(right)
            if key not in allowed
        ):
            return False
    return True


def apply_ai(runtime, before, after, rows, changed, directory, write_private):
    api = runtime.docker_api if runtime.docker_api is not None else DockerAPI()
    token = uuid.uuid4().hex[:16]
    entries = []

    def journal():
        # Immutable steps are useful even if the controller dies before its receipt.
        write_private(directory / ("exact-" + uuid.uuid4().hex + ".json"), entries)

    try:
        # Preflight every identity/payload before touching any canonical worker.
        for name in changed:
            row = api.inspect(rows[name]["Id"])
            if row != rows[name]:
                # State timestamps can change, but identity/config/mounts must not.
                for field in ("Id", "Name", "Image", "Config", "HostConfig", "Mounts"):
                    if row.get(field) != rows[name].get(field):
                        raise ValueError("AI container changed during settings apply")
            payload = clone_payload(
                row, dict(item.split("=", 1) for item in row["Config"]["Env"])
            )
            live_env = dict(item.split("=", 1) for item in row["Config"]["Env"])
            old_env, new_env = (
                before["services"][name]["environment"],
                after["services"][name]["environment"],
            )
            live_env.update(
                {
                    key: str(value)
                    for key, value in new_env.items()
                    if old_env.get(key) != value
                }
            )
            payload["Env"] = [key + "=" + value for key, value in live_env.items()]
            entries.append(
                {
                    "old": row["Id"],
                    "name": row["Name"].lstrip("/"),
                    "new": None,
                    "config": row["Config"],
                    "restart": row["HostConfig"]["RestartPolicy"],
                    "payload": payload,
                }
            )
        journal()
        for entry in entries:
            candidate = entry["name"] + "-settings-new-" + token
            entry["new"] = api.create(candidate, entry["payload"])
            journal()
            created = api.inspect(entry["new"])
            expected_config = {
                key: value
                for key, value in entry["payload"].items()
                if key not in {"HostConfig", "NetworkingConfig"}
            }
            expected_host = deepcopy(entry["payload"]["HostConfig"])
            if (
                expected_host.get("OomKillDisable") is None
                and created["HostConfig"].get("OomKillDisable") is False
            ):
                expected_host["OomKillDisable"] = False
            if (
                created["Name"] != "/" + candidate
                or created["State"]["Running"]
                or created["Config"] != expected_config
                or created["HostConfig"] != expected_host
            ):
                raise ValueError("AI candidate did not preserve its container contract")
            fresh = api.inspect(entry["old"])
            if (
                fresh["Name"] != "/" + entry["name"]
                or fresh["Config"] != entry["config"]
            ):
                raise ValueError("AI canonical identity drifted")
            api.action(
                entry["old"],
                "update",
                {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
            )
            api.action(entry["old"], "stop", t=30)
            api.action(
                entry["old"], "rename", name=entry["name"] + "-settings-old-" + token
            )
            api.action(entry["new"], "rename", name=entry["name"])
            api.action(entry["new"], "start")
            journal()
        if not runtime.wait_ready(after):
            raise RuntimeError("AI settings readiness failed")
        for entry in entries:
            api.action(entry["new"], "update", {"RestartPolicy": entry["restart"]})
        staged = directory / "active.json"
        write_private(staged, after)
        os.replace(staged, runtime.active)
        return "applied"
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        try:
            for entry in reversed(entries):
                if not entry["new"]:
                    continue
                api.action(
                    entry["new"],
                    "update",
                    {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
                )
                api.action(entry["new"], "stop", t=30)
                api.action(
                    entry["new"],
                    "rename",
                    name=entry["name"] + "-settings-failed-" + token,
                )
                old = api.inspect(entry["old"])
                if old["Name"] not in {
                    "/" + entry["name"],
                    "/" + entry["name"] + "-settings-old-" + token,
                }:
                    return "interrupted"
                if old["Name"] != "/" + entry["name"]:
                    api.action(entry["old"], "rename", name=entry["name"])
                api.action(entry["old"], "update", {"RestartPolicy": entry["restart"]})
                if not old["State"]["Running"]:
                    api.action(entry["old"], "start")
            return "rolled_back" if runtime.wait_ready(before) else "interrupted"
        except (
            OSError,
            ValueError,
            KeyError,
            RuntimeError,
            subprocess.SubprocessError,
        ):
            return "interrupted"
