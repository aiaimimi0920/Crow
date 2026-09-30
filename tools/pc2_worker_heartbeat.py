"""Read-only worker progress evidence, using the worker's own clock and paths."""

import json
import math

from .pc2_settings_runtime import run

HEARTBEAT_PROBE = """
import json,os,time
from pathlib import Path
p=Path(os.environ.get('FAPAI_WORKER_HEARTBEAT_PATH','/tmp/fapaifang-worker-heartbeat.json'))
h=json.loads(p.read_text(encoding='utf-8'))
os.kill(int(h['pid']),0)
keys=('worker_id','pid','stage','updated_at_epoch')
print(json.dumps({**{k:h[k] for k in keys},'observed_at_epoch':time.time(),
 'stale_seconds':float(os.environ.get('FAPAI_WORKER_HEARTBEAT_STALE_SECONDS','900'))}))
"""


def read_heartbeat(container_id, *, runner=run):
    return json.loads(
        runner(["exec", container_id, "python", "-c", HEARTBEAT_PROBE], timeout=15)
    )


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def stale_heartbeat(value, service):
    """Return stable evidence only for a matching, alive worker with stale progress."""
    if not isinstance(value, dict) or value.get("worker_id") != service:
        raise ValueError("Worker heartbeat identity mismatch")
    if type(value.get("pid")) is not int or value["pid"] < 1:
        raise ValueError("Invalid worker heartbeat PID")
    if not isinstance(value.get("stage"), str) or not value["stage"]:
        raise ValueError("Invalid worker heartbeat stage")
    updated, observed, maximum = (
        value.get(k) for k in ("updated_at_epoch", "observed_at_epoch", "stale_seconds")
    )
    if not all(finite_number(v) for v in (updated, observed, maximum)) or maximum < 1:
        raise ValueError("Invalid worker heartbeat time")
    if value["stage"] == "stopped" or observed - updated <= max(900, maximum):
        return None
    return {k: value[k] for k in ("worker_id", "pid", "stage", "updated_at_epoch")}
