"""Fixed operator routes from the TLS gateway to the same-host collection API."""

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request

from src.collection_engine_restart import RestartError, token
from src.collection_operator_actions import (
    OPERATOR_ACTION_PATHS,
    validate_operator_body,
)
from src.project_environment import getenv as project_getenv

RUNTIME_ROUTES = frozenset(OPERATOR_ACTION_PATHS.values())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def runtime_origin():
    value = project_getenv("CROW_CONTROL_LOCAL_API_BASE", "")
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
        valid = (
            parsed.scheme == "http"
            and address.is_loopback
            and not getattr(address, "scope_id", None)
            and port
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
        )
    except ValueError:
        valid = False
    if not valid:
        raise RestartError("Local runtime control is not configured", 503)
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{host}:{port}"


def forward_runtime(method, path, body):
    if method != "POST" or path not in RUNTIME_ROUTES:
        raise RestartError("Unsupported runtime action", 405)
    action = next(
        action for action, route in OPERATOR_ACTION_PATHS.items() if route == path
    )
    # Select the server-owned route, rather than forwarding caller URL text.
    # The caller can choose an action but cannot supply any part of its URL.
    canonical_path = OPERATOR_ACTION_PATHS[action]
    try:
        validate_operator_body(action, body)
    except ValueError:
        raise RestartError("Invalid operator body", 400) from None
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(raw) > 16384:
        raise RestartError("Operator body is too large", 413)
    credential = token("operator")
    if not credential:
        raise RestartError("Operator token is not configured", 503)
    request = urllib.request.Request(
        runtime_origin() + canonical_path,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-FAPAI-Control-Token": credential,
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise RestartError("Invalid runtime response", 502)
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RestartError("Runtime action was not confirmed", 502)
            return result
    except urllib.error.HTTPError as error:
        status = error.code if error.code in {400, 401, 403, 409, 503} else 502
        raise RestartError("Runtime request rejected", status) from None
    except (OSError, ValueError) as error:
        raise RestartError("Runtime request unavailable", 502) from error
