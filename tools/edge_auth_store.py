"""Local task mailbox. No listening port and no background browser access."""

import json
import os
import secrets
import tempfile
import time

from tools.edge_auth_contract import MAX_MESSAGE, TASK_TTL, identity, normalize_cookies
from tools.manual_auth_snapshot import completion_lock
from tools.pc1_desktop_recovery import RecoveryError


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read(path):
    try:
        if path.stat().st_size > MAX_MESSAGE:
            raise ValueError
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecoveryError("edge_task_missing") from error


def task_root(data_root):
    return data_root / "secrets" / "edge-auth"


def create_task(root, *, request_id, url, scope, api, challenge_id):
    from tools.pc1_desktop_auth import target_identity

    identity(request_id)
    if (
        scope not in {"seed", "detail"}
        or target_identity(url)[0]
        != {"seed": "sf.taobao.com", "detail": "sf-item.taobao.com"}[scope]
    ):
        raise RecoveryError("invalid_target")
    with completion_lock(root / "mailbox"):
        task = {
            "request_id": request_id,
            "nonce": secrets.token_hex(16),
            "target_url": url,
            "scope": scope,
            "api": api,
            "challenge_id": challenge_id,
            "expires": time.time() + TASK_TTL,
            "submitted": False,
        }
        save(root / "task.json", task)
    return task


def current_task(root):
    task = read(root / "task.json")
    if not isinstance(task, dict) or not isinstance(task.get("expires"), (int, float)):
        raise RecoveryError("edge_task_missing")
    if not time.time() < task["expires"] <= time.time() + TASK_TTL + 1:
        raise RecoveryError("edge_task_expired")
    return task


def handle(root, message):
    from tools.pc1_desktop_auth import target_identity

    if not isinstance(message, dict) or message.get("action") not in {
        "claim",
        "submit",
    }:
        raise RecoveryError("edge_invalid_request")
    profile = identity(message.get("profile_id"))
    with completion_lock(root / "mailbox"):
        task = current_task(root)
        binding = root / "profile.json"
        if binding.exists() and read(binding).get("profile_id") != profile:
            raise RecoveryError("edge_wrong_profile")
        if message["action"] == "claim":
            if not binding.exists():
                save(binding, {"profile_id": profile})
            return {
                key: task[key]
                for key in ("request_id", "nonce", "target_url", "scope", "expires")
            }
        if not binding.exists():
            raise RecoveryError("edge_wrong_profile")
        if task["submitted"]:
            raise RecoveryError("edge_already_submitted")
        if any(message.get(key) != task[key] for key in ("request_id", "nonce")):
            raise RecoveryError("edge_task_changed")
        if target_identity(message.get("tab_url", "")) != target_identity(
            task["target_url"]
        ):
            raise RecoveryError("challenge_page_not_ready")
        raw = normalize_cookies(message.get("cookies"))
        ua = message.get("user_agent")
        if (
            not isinstance(ua, str)
            or not 0 < len(ua) <= 1024
            or any(ord(c) < 32 for c in ua)
        ):
            raise RecoveryError("edge_invalid_request")
        # Contains no arbitrary destination or NAS credentials from the extension.
        save(
            root / (task["request_id"] + ".json"),
            {**task, "cookies": json.loads(raw), "user_agent": ua, "submitted": True},
        )
        task["submitted"] = True
        save(root / "task.json", task)
        return {"submitted": True}


def capture(root, *, request_id, api, scope, url, challenge_id):
    from tools.pc1_desktop_auth import target_identity
    from tools.taobao_inplace_auth_handoff import _validate_cookie_http

    identity(request_id)
    with completion_lock(root / "mailbox"):
        task = current_task(root)
        if task["request_id"] != request_id:
            raise RecoveryError("edge_task_changed")
        value = read(root / (request_id + ".json"))
        if any(
            value.get(key) != expected
            for key, expected in {
                "nonce": task["nonce"],
                "api": api,
                "scope": scope,
                "challenge_id": challenge_id,
                "submitted": True,
            }.items()
        ) or target_identity(value["target_url"]) != target_identity(url):
            raise RecoveryError("edge_task_changed")
    health = _validate_cookie_http(
        value["cookies"],
        url if scope == "detail" else "",
        user_agent=value["user_agent"],
        allow_list_only=scope == "seed",
        scope=scope,
        target_url=url,
    )
    if health.get("healthy") is not True:
        raise RecoveryError("session_not_reusable")
    with completion_lock(root / "mailbox"):
        latest = current_task(root)
        if latest["nonce"] != value["nonce"] or latest["request_id"] != request_id:
            raise RecoveryError("edge_task_changed")
    return json.dumps(value["cookies"], ensure_ascii=True).encode("utf-8")
