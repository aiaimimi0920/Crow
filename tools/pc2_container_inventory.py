"""Canonical PC2 identities; retained stopped release backups are not targets."""
import re

from .pc2_settings_model import WORKER

PROJECT = "fapaifang-pc2"
BROWSER = "pc2-browser-solver"


def canonical_containers(rows):
    if not isinstance(rows, list):
        raise ValueError("Invalid collection inventory")
    result = {}
    for row in rows:
        labels = row.get("Config", {}).get("Labels", {})
        service = labels.get("com.docker.compose.service", "")
        if (labels.get("com.docker.compose.project") != PROJECT
                or not isinstance(service, str) or not (service == BROWSER or WORKER.fullmatch(service))
                or not re.fullmatch(r"[a-f0-9]{64}", row.get("Id", ""))):
            raise ValueError("Unexpected collection container identity")
        if row.get("Name") != "/fapaifang-" + service:
            state = row.get("State", {})
            if state.get("Status") in {"created", "exited", "dead"} and not state.get("Running"):
                continue
            raise ValueError("Noncanonical collection container is active or unidentified")
        if service in result:
            raise ValueError("Duplicate canonical collection identity")
        result[service] = row
    return result


def require_compose_safe_inventory(rows, services):
    """Compose rediscovers labels, so filtering backups from reads is insufficient."""
    canonical_containers(rows)
    targets = set(services)
    for row in rows:
        service = row["Config"]["Labels"]["com.docker.compose.service"]
        if service in targets and row.get("Name") != "/fapaifang-" + service:
            raise ValueError(
                "Retained collection backups require exact-ID deployment; "
                "refusing service-wide Compose recreation"
            )
