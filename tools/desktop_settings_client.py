"""Private-CA settings transport. Secrets travel on stdin, never command lines."""
import json
from pathlib import Path
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.desktop_runtime_config import load_runtime_environment
from tools.pc1_desktop_recovery import RecoveryError, NoRedirect
from tools.desktop_environment import environment_value
from src.collection_settings_schema import validate, validate_key
from src.collection_engine_restart import RestartError
from src.collection_operator_actions import OPERATOR_ACTION_PATHS, validate_operator_body


def origin(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"} or parsed.port == 0):
        raise ValueError("invalid_control_origin")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def execute(request, root):
    if not isinstance(request, dict) or set(request) - {"action", "origin", "body"}:
        raise ValueError("invalid_request")
    action = request.get("action")
    if action not in {"config", "get", "apply", "restart_status", "restart"} | OPERATOR_ACTION_PATHS.keys():
        raise ValueError("invalid_action")
    env = load_runtime_environment(root)
    configured = origin(environment_value('CROW_SETTINGS_API_BASE', '', environment=env, root=Path(root)))
    ca = Path(environment_value('CROW_SETTINGS_CA_FILE', '', environment=env, root=Path(root)))
    token_file = Path(environment_value('CROW_ENGINE_OPERATOR_TOKEN_FILE', '', environment=env, root=Path(root)))
    if action == "config":
        return {"ok": True, "origin": configured, "configured": ca.is_file() and token_file.is_file()}
    if origin(request.get("origin", "")) != configured:
        raise ValueError("control_origin_not_configured")
    token = token_file.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", token):
        raise ValueError("control_token_invalid")
    body = request.get("body")
    if action == "apply":
        if not isinstance(body, dict) or set(body) != {"request_id", "expected_revision", "config", "api_key"}:
            raise ValueError("invalid_apply")
        if not isinstance(body["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", body["request_id"]):
            raise ValueError("invalid_request_id")
        if type(body["expected_revision"]) is not int or body["expected_revision"] < 0:
            raise ValueError("invalid_revision")
        validate(body["config"])
        validate_key(body["api_key"])
    elif action == "restart":
        if not isinstance(body, dict) or set(body) != {"request_id"}:
            raise ValueError("invalid_restart")
        if not isinstance(body["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", body["request_id"]):
            raise ValueError("invalid_request_id")
    elif action in OPERATOR_ACTION_PATHS:
        validate_operator_body(action, body)
    elif body is not None:
        raise ValueError("unexpected_body")
    context = ssl.create_default_context(cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context))
    read_only = action in {"get", "restart_status"}
    raw = None if read_only else json.dumps(body).encode("utf-8")
    if raw is not None and len(raw) > 16384:
        raise ValueError("oversized_request")
    url = configured + "/api/collection/settings" + ("/apply" if action == "apply" else "")
    if action in {"restart_status", "restart"}:
        url = configured + "/api/collection/control/restart"
    elif action in OPERATOR_ACTION_PATHS:
        url = configured + OPERATOR_ACTION_PATHS[action]
    query = urllib.request.Request(url, data=raw, method="GET" if read_only else "POST",
                                   headers={"Content-Type": "application/json", "X-FAPAI-Control-Token": token})
    try:
        with opener.open(query, timeout=20) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized_response")
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("ok") is not True:
                raise ValueError("invalid_response")
            return value
    except urllib.error.HTTPError as error:
        return {"ok": False, "error": "control_http_error", "status": error.code}


def main():
    try:
        raw = sys.stdin.buffer.read(20001)
        if len(raw) > 20000:
            raise ValueError("oversized_input")
        result = execute(json.loads(raw), Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TypeError, KeyError, RecoveryError, RestartError):
        # Never include raw exceptions, remote bodies, credentials or request data.
        result = {"ok": False, "error": "control_transport_unavailable"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
