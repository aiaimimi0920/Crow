from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from tools.internal_api_http import fetch_json, post_json
from tools.pc2_detail_auth_probe import probe_detail_access
from tools.pc2_seed_auth_probe import probe_seed_access


# Chromium pages legitimately rotate or remove analytics cookies immediately
# after Storage.setCookies.  These stable session cookies are the fail-closed
# anchors that prove the reusable Taobao session itself survived the import.
TAOBAO_SESSION_COOKIE_NAMES = frozenset(
    {"_tb_token_", "cookie1", "cookie2", "cookie17", "sgcookie", "t", "unb"}
)


def _recovery_url(api_base_url: str, suffix: str = "") -> str:
    base = api_base_url.rstrip("/") + "/collection/auth/recovery"
    return base + suffix


def load_recovery_token(token_path: str | Path) -> str:
    token = Path(token_path).read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("NAS auth recovery token file is empty")
    if (
        not 16 <= len(token) <= 4096
        or not token.isascii()
        or any(char.isspace() for char in token)
    ):
        raise ValueError("NAS auth recovery token is invalid")
    return token


def load_cookie_snapshot(
    snapshot_path: str | Path,
    *,
    expected_sha256: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(snapshot_path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = str(expected_sha256 or "").strip().lower()
    if expected and digest != expected:
        raise ValueError("cookie snapshot digest does not match the NAS recovery metadata")
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("cookie snapshot must contain a non-empty JSON list")
    cookies = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("cookie snapshot entries must be objects")
        name = str(item.get("name") or "").strip()
        value = item.get("value")
        domain = str(item.get("domain") or "").strip().lower()
        if not name or not isinstance(value, str) or not domain:
            raise ValueError("cookie snapshot entry is missing name, value, or domain")
        if not (domain == "taobao.com" or domain.endswith(".taobao.com")):
            continue
        cookies.append(dict(item))
    if not cookies:
        raise ValueError("cookie snapshot contains no Taobao cookies")
    return cookies, {"sha256": digest, "cookie_count": len(cookies)}


def ensure_cookie_snapshot(
    api_base_url: str,
    recovery_id: str,
    snapshot_path: str | Path,
    *,
    expected_sha256: str,
    headers: dict[str, str],
    fetcher: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    path = Path(snapshot_path)
    try:
        _, metadata = load_cookie_snapshot(path, expected_sha256=expected_sha256)
        return {**metadata, "source": "local"}
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    payload = fetcher(
        _recovery_url(api_base_url, f"/snapshot?recovery_id={quote(recovery_id, safe='')}"),
        timeout=20,
        headers=headers,
    )
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise OSError("NAS did not return the requested authentication snapshot")
    if str(payload.get("recovery_id") or "") != recovery_id:
        raise ValueError("NAS authentication snapshot belongs to a different recovery")
    if str(payload.get("encoding") or "") != "base64":
        raise ValueError("NAS authentication snapshot encoding is unsupported")
    encoded = payload.get("snapshot")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("NAS authentication snapshot payload is empty")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("NAS authentication snapshot payload is invalid") from exc
    digest = hashlib.sha256(raw).hexdigest()
    expected = str(expected_sha256 or "").strip().lower()
    if not expected or digest != expected or str(payload.get("sha256") or "").lower() != expected:
        raise ValueError("downloaded authentication snapshot digest does not match recovery metadata")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(raw)
        temporary.chmod(0o600)
        _, metadata = load_cookie_snapshot(temporary, expected_sha256=expected)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {**metadata, "source": "nas"}


def _cookie_param(cookie: dict[str, Any]) -> dict[str, Any]:
    param: dict[str, Any] = {
        "name": str(cookie["name"]),
        "value": str(cookie["value"]),
        "domain": str(cookie["domain"]),
        "path": str(cookie.get("path") or "/"),
        "secure": bool(cookie.get("secure", False)),
        "httpOnly": bool(cookie.get("httpOnly", False)),
    }
    expires = cookie.get("expires")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0:
        param["expires"] = float(expires)
    same_site = str(cookie.get("sameSite") or "").strip().capitalize()
    if same_site in {"Strict", "Lax", "None"}:
        param["sameSite"] = same_site
    priority = str(cookie.get("priority") or "").strip().capitalize()
    if priority in {"Low", "Medium", "High"}:
        param["priority"] = priority
    return param


def _cdp_call(websocket_connection: Any, message_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    websocket_connection.send(
        json.dumps(
            {"id": message_id, "method": method, "params": params},
            ensure_ascii=False,
        )
    )
    while True:
        response = json.loads(websocket_connection.recv())
        if response.get("id") != message_id:
            continue
        if isinstance(response.get("error"), dict):
            raise OSError(f"CDP {method} failed: {response['error'].get('message', 'unknown error')}")
        result = response.get("result")
        return dict(result) if isinstance(result, dict) else {}


def import_cookie_snapshot_to_cdp(
    snapshot_path: str | Path,
    cdp_endpoint: str,
    *,
    expected_sha256: str = "",
) -> dict[str, Any]:
    cookies, metadata = load_cookie_snapshot(
        snapshot_path,
        expected_sha256=expected_sha256,
    )
    version = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/version", timeout=5)
    websocket_url = str((version or {}).get("webSocketDebuggerUrl") or "").strip()
    if not websocket_url:
        raise OSError("Chromium browser websocket endpoint is unavailable")

    import websocket

    connection = websocket.create_connection(
        websocket_url,
        suppress_origin=True,
        timeout=10,
    )
    try:
        connection.settimeout(10)
        params = [_cookie_param(cookie) for cookie in cookies]
        _cdp_call(connection, 1, "Storage.setCookies", {"cookies": params})
        stored = _cdp_call(connection, 2, "Storage.getCookies", {}).get("cookies")
        stored_cookies = stored if isinstance(stored, list) else []
        expected_keys = {
            (str(cookie["name"]), str(cookie["domain"]), str(cookie.get("path") or "/"))
            for cookie in params
        }
        stored_keys = {
            (
                str(cookie.get("name") or ""),
                str(cookie.get("domain") or ""),
                str(cookie.get("path") or "/"),
            )
            for cookie in stored_cookies
            if isinstance(cookie, dict)
        }
        verified_count = len(expected_keys & stored_keys)
        expected_session_keys = {
            key for key in expected_keys if key[0] in TAOBAO_SESSION_COOKIE_NAMES
        }
        stored_session_keys = expected_session_keys & stored_keys
        if expected_session_keys and stored_session_keys != expected_session_keys:
            raise OSError(
                "Chromium did not retain every expected Taobao session cookie identity "
                f"({len(stored_session_keys)} of {len(expected_session_keys)})"
            )
        if not expected_session_keys and verified_count < len(expected_keys):
            raise OSError(
                f"Chromium stored only {verified_count} of {len(expected_keys)} expected cookie identities"
            )
        return {
            **metadata,
            "imported_count": len(params),
            "verified_count": verified_count,
            "session_cookie_count": len(expected_session_keys),
            "verified_session_cookie_count": len(stored_session_keys),
        }
    finally:
        connection.close()


def _write_marker(marker_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(marker_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_marker(marker_path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(marker_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def process_nas_auth_recovery_once(
    api_base_url: str,
    cdp_endpoint: str,
    node_id: str,
    snapshot_path: str | Path,
    marker_path: str | Path,
    token_path: str | Path,
    *,
    fetcher: Callable[..., Any] = fetch_json,
    poster: Callable[..., Any] = post_json,
) -> dict[str, Any]:
    token = load_recovery_token(token_path)
    headers = {"X-Fapai-Recovery-Token": token}
    if str(node_id or '').strip().lower() == 'pc2':
        heartbeat = poster(
            _recovery_url(api_base_url, '/heartbeat'),
            {'protocol_version': 2, 'node_id': 'pc2'}, timeout=10, headers=headers,
        )
        if not isinstance(heartbeat, dict) or heartbeat.get('ok') is not True:
            return {'action': 'ignored', 'reason': 'heartbeat_rejected'}
    response = fetcher(_recovery_url(api_base_url), timeout=10, headers=headers)
    recovery_status = response.get("auth_recovery") if isinstance(response, dict) else None
    active = recovery_status.get("active") if isinstance(recovery_status, dict) else None
    if not isinstance(active, dict):
        Path(marker_path).unlink(missing_ok=True)
        return {"action": "idle"}

    recovery_id = str(active.get("recovery_id") or "").strip()
    status = str(active.get("status") or "").strip()
    snapshot = active.get("snapshot") if isinstance(active.get("snapshot"), dict) else {}
    expected_sha256 = str(snapshot.get("sha256") or "").strip().lower()
    if not recovery_id:
        return {"action": "ignored", "reason": "missing_recovery_id"}
    if str(node_id or "").strip().lower() != "pc2":
        return {"action": "ignored", "reason": "node_is_not_pc2", "recovery_id": recovery_id}

    if status == "snapshot_ready":
        claimed = poster(
            _recovery_url(api_base_url, "/claim"),
            {"recovery_id": recovery_id, "role": "pc2", "node_id": "pc2"},
            timeout=10,
            headers=headers,
        )
        if not isinstance(claimed, dict) or claimed.get("ok") is not True:
            raise OSError("NAS did not acknowledge the PC2 claim")
        status = "pc2_claimed"

    imported = None
    if status == "pc2_claimed":
        ensure_cookie_snapshot(
            api_base_url,
            recovery_id,
            snapshot_path,
            expected_sha256=expected_sha256,
            headers=headers,
            fetcher=fetcher,
        )
        imported = import_cookie_snapshot_to_cdp(
            snapshot_path,
            cdp_endpoint,
            expected_sha256=expected_sha256,
        )
        marker = {
            "schema_version": 1,
            "recovery_id": recovery_id,
            "snapshot_sha256": imported["sha256"],
            "cookie_count": imported["cookie_count"],
            "imported_at_epoch": time.time(),
        }
        _write_marker(marker_path, marker)
        acknowledged = poster(
            _recovery_url(api_base_url, "/pc2_restarting"),
            {"recovery_id": recovery_id, "node_id": "pc2"},
            timeout=10,
            headers=headers,
        )
        if not isinstance(acknowledged, dict) or acknowledged.get("ok") is not True:
            raise OSError("NAS did not acknowledge the PC2 verification phase")
        if not active.get("scope"):
            return {
                "action": "restart_requested",
                "recovery_id": recovery_id,
                "cookie_count": imported["cookie_count"],
            }
        # Scoped handoffs already imported and verified cookies through CDP.
        # Validate a fresh page in that browser; restarting it discards useful
        # session state and can strand the receipt while CDP is unavailable.
        status = "restarting"

    if status == "restarting" and imported is None:
        ensure_cookie_snapshot(
            api_base_url,
            recovery_id,
            snapshot_path,
            expected_sha256=expected_sha256,
            headers=headers,
            fetcher=fetcher,
        )
        marker = _read_marker(marker_path)
        if str(marker.get("recovery_id") or "") != recovery_id:
            imported = import_cookie_snapshot_to_cdp(
                snapshot_path,
                cdp_endpoint,
                expected_sha256=expected_sha256,
            )
            _write_marker(
                marker_path,
                {
                    "schema_version": 1,
                    "recovery_id": recovery_id,
                    "snapshot_sha256": imported["sha256"],
                    "cookie_count": imported["cookie_count"],
                    "imported_at_epoch": time.time(),
                    "marker_recovered": True,
                },
            )
        else:
            imported = import_cookie_snapshot_to_cdp(
                snapshot_path,
                cdp_endpoint,
                expected_sha256=expected_sha256,
            )
    if status == "restarting":
        stage_receipt = {}
        if active.get("scope"):
            scope = active["scope"]
            try:
                probe = probe_seed_access if scope == "seed" else probe_detail_access
                authenticated = probe(cdp_endpoint, active.get("target_url", ""))
                reason = f"{scope}_payload_verified" if authenticated else "stage_probe_failed"
            except Exception:
                authenticated = False
                reason = "stage_probe_unavailable"
            stage_receipt = {
                "scope": scope, "protocol_version": 2,
                "snapshot_sha256": expected_sha256, "target_url": active.get("target_url"),
                "probe_authenticated": authenticated, "success": authenticated,
                "reason": reason,
            }
        result = poster(
            _recovery_url(api_base_url, "/result"),
            {
                "recovery_id": recovery_id,
                "node_id": "pc2",
                "success": True,
                "reason": "cookie_import_verified_after_restart",
                **stage_receipt,
            },
            timeout=15,
            headers=headers,
        )
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise OSError("NAS did not acknowledge the PC2 recovery result")
        if active.get("scope") and result.get("status") == "failed":
            return {"action": "recovery_failed", "recovery_id": recovery_id, "scope": active["scope"]}
        if active.get("scope") == "seed" and result.get("status") != "succeeded":
            raise OSError("NAS has not confirmed seed access")
        Path(marker_path).unlink(missing_ok=True)
        return {
            "action": (
                "recovery_verifying"
                if active.get("scope") == "detail" and result.get("status") == "verifying"
                else "recovery_confirmed"
            ),
            "recovery_id": recovery_id,
            "cookie_count": imported["cookie_count"],
            "scope": active.get("scope"),
        }

    if status == "verifying":
        Path(marker_path).unlink(missing_ok=True)
        return {"action": "waiting_for_collection_progress", "recovery_id": recovery_id}
    return {"action": "ignored", "reason": f"status_{status}", "recovery_id": recovery_id}
