"""Bind successful cookie imports to one recovery, snapshot and browser instance."""

import hashlib
import re


def browser_instance(version):
    url = str((version or {}).get("webSocketDebuggerUrl") or "").strip()
    if not re.match(r"^wss?://[^/]+/devtools/browser/[^/?#]+$", url):
        return ""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def reusable_import(marker, recovery_id, digest, endpoint, fetch_version):
    if (
        marker.get("schema_version") != 2
        or marker.get("recovery_id") != recovery_id
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or marker.get("snapshot_sha256") != digest
        or marker.get("cdp_endpoint") != endpoint.rstrip("/")
        or not marker.get("browser_instance")
        or type(marker.get("cookie_count")) is not int
        or marker["cookie_count"] <= 0
    ):
        return None
    current = browser_instance(fetch_version())
    if not current or current != marker["browser_instance"]:
        return None
    return {"sha256": digest, "cookie_count": marker["cookie_count"]}


def import_receipt(imported, recovery_id, endpoint, now):
    return {
        "schema_version": 2,
        "recovery_id": recovery_id,
        "snapshot_sha256": imported["sha256"],
        "cookie_count": imported["cookie_count"],
        "browser_instance": imported.get("browser_instance", ""),
        "cdp_endpoint": endpoint.rstrip("/"),
        "imported_at_epoch": now,
    }
