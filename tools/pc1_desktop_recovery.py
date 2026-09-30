"""Protected, metadata-only client for an explicitly configured NAS auth endpoint."""

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from src.auth_recovery_codes import (
    CHALLENGE_CHANGED_CODE,
    TERMINAL_CODE,
    UNKNOWN_RECOVERY_CODE,
    active_code,
    failure_code,
)
from src.auth_snapshot_contract import RecoveryError
from src.collection_api_credentials import secure_api_origin
from tools.desktop_environment import environment_value


def api_origin(value):
    try:
        return secure_api_origin(value)
    except (TypeError, ValueError) as error:
        raise RecoveryError("invalid_api") from error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RecoveryError("redirect_refused")


class RecoveryClient:
    def __init__(self, api_base, data_root, *, environment=None):
        environment = os.environ if environment is None else environment
        configured = environment_value(
            "CROW_COLLECTOR_API_BASE", environment=environment, root=Path(data_root)
        ) or environment_value(
            "CROW_API_BASE_URL", environment=environment, root=Path(data_root)
        )
        if not configured or api_origin(api_base) != api_origin(configured):
            raise RecoveryError("api_not_configured")
        self.origin = api_origin(api_base)
        self.url = self.origin + "/api/collection/auth/recovery"
        try:
            context = ssl.create_default_context(
                cafile=environment_value(
                    "CROW_API_CA_FILE", environment=environment, root=Path(data_root)
                )
                or None
            )
        except (OSError, ValueError) as error:
            raise RecoveryError("ca_unavailable") from error
        self.token_path = Path(
            environment_value(
                "CROW_NAS_AUTH_RECOVERY_TOKEN_FILE",
                environment=environment,
                root=Path(data_root),
            )
            or data_root / "secrets" / "nas-auth-recovery.token"
        )
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
        )
        _ = self.headers

    @property
    def headers(self):
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise RecoveryError("token_unavailable") from error
        if (
            not 16 <= len(token) <= 4096
            or not token.isascii()
            or any(char.isspace() for char in token)
        ):
            raise RecoveryError("token_unavailable")
        return {"X-Fapai-Recovery-Token": token, "Content-Type": "application/json"}

    def call(self, path="", body=None):
        return self._request(self.url + path, body, require_ok=True)

    def status(self):
        return self._request(self.origin + "/api/status", None, require_ok=False)

    def _request(self, url, body, *, require_ok):
        request = urllib.request.Request(
            url,
            headers=self.headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise RecoveryError("invalid_response")
            value = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise RecoveryError(
                {
                    403: "token_rejected",
                    404: "api_upgrade_required",
                    409: "challenge_changed",
                    412: "pc2_stage_upgrade_required",
                    423: "handoff_busy",
                }.get(error.code, "api_unavailable")
            ) from error
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise RecoveryError("api_unavailable") from error
        if not isinstance(value, dict) or (require_ok and value.get("ok") is not True):
            raise RecoveryError("request_rejected")
        return value


def recovery_phase(snapshot, recovery_id, *, scope=""):
    if not isinstance(snapshot, dict):
        return {
            "phase": "unavailable",
            "code": UNKNOWN_RECOVERY_CODE,
            "recovery_id": recovery_id,
        }
    active = snapshot.get("active")
    last = snapshot.get("last_result")
    active = active if isinstance(active, dict) else {}
    last = last if isinstance(last, dict) else {}
    matched = active if active.get("recovery_id") == recovery_id else last
    if scope and matched.get("scope") != scope:
        return {
            "phase": "failed",
            "code": CHALLENGE_CHANGED_CODE,
            "recovery_id": recovery_id,
        }
    if active.get("recovery_id") == recovery_id:
        code = active_code(active.get("status"), scoped=bool(scope))
        if code is None:
            return {
                "phase": "unavailable",
                "code": "invalid_response",
                "recovery_id": recovery_id,
            }
        return {"phase": "pending_pc2", "recovery_id": recovery_id, "code": code}
    if last.get("recovery_id") == recovery_id:
        code = (
            TERMINAL_CODE
            if last.get("status") == "succeeded"
            else failure_code(last.get("reason"))
        )
        return {
            "phase": "succeeded" if last.get("status") == "succeeded" else "failed",
            "recovery_id": recovery_id,
            "code": code,
        }
    return {
        "phase": "unavailable",
        "code": UNKNOWN_RECOVERY_CODE,
        "recovery_id": recovery_id,
    }
