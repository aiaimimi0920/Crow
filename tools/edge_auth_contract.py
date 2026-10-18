"""Bounded, source-specific import from an explicitly approved Edge task."""

import json
import math
import re

from tools.pc1_desktop_recovery import RecoveryError

EXTENSION_ID = "hkpcgieobdbcophagofgeglpiofmedhg"
HOST_NAME = "com.crow.manual_auth"
MAX_MESSAGE = 512 * 1024
TASK_TTL = 600
COOKIE_HOSTS = {
    "taobao.com",
    "sf.taobao.com",
    "sf-item.taobao.com",
    "susong-item.taobao.com",
    "login.taobao.com",
}


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise RecoveryError("edge_invalid_request")
    return value


def normalize_cookies(values):
    if not isinstance(values, list) or not 0 < len(values) <= 500:
        raise RecoveryError("invalid_snapshot")
    result, seen = [], set()
    same_site = {
        "no_restriction": "None",
        "lax": "Lax",
        "strict": "Strict",
        "unspecified": "Lax",
    }
    for value in values:
        if not isinstance(value, dict):
            raise RecoveryError("invalid_snapshot")
        domain = value.get("domain", "")
        if not isinstance(domain, str) or domain.lstrip(".") not in COOKIE_HOSTS:
            raise RecoveryError("edge_cookie_scope")
        if value.get("partitionKey") is not None:
            raise RecoveryError("edge_partition_unsupported")
        cookie = {key: value.get(key) for key in ("name", "value", "domain", "path")}
        if any(not isinstance(item, str) for item in cookie.values()):
            raise RecoveryError("invalid_snapshot")
        if not cookie["name"] or not cookie["path"].startswith("/"):
            raise RecoveryError("invalid_snapshot")
        if any(
            len(item) > 16384 or any(ord(c) < 32 for c in item)
            for item in cookie.values()
        ):
            raise RecoveryError("invalid_snapshot")
        for key in ("secure", "httpOnly"):
            if not isinstance(value.get(key), bool):
                raise RecoveryError("invalid_snapshot")
            cookie[key] = value[key]
        site = value.get("sameSite")
        if site not in same_site:
            raise RecoveryError("invalid_snapshot")
        cookie["sameSite"] = same_site[site]
        expiry = value.get("expirationDate", -1)
        if (
            isinstance(expiry, bool)
            or not isinstance(expiry, (int, float))
            or not math.isfinite(expiry)
        ):
            raise RecoveryError("invalid_snapshot")
        cookie["expires"] = expiry
        key = (domain, cookie["path"], cookie["name"])
        if key in seen:
            raise RecoveryError("invalid_snapshot")
        seen.add(key)
        result.append(cookie)
    raw = json.dumps(result, ensure_ascii=True).encode("utf-8")
    if len(raw) > MAX_MESSAGE:
        raise RecoveryError("invalid_snapshot")
    return raw
