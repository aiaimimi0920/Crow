"""Fresh, read-only collection evidence from the installed browser environment."""

import json
import math

from .pc2_settings_runtime import run

# Execute inside the existing container so credential and CA ownership stay there.
STATUS_PROBE = """
import json,os
from tools.internal_api_http import fetch_json
status=fetch_json(os.environ['FAPAI_API_BASE_URL'].rstrip('/')+'/status',timeout=15)
keys=('statistics','paused','collection_scopes','auth_recovery','captcha_solver',
      'captured_count','seed_occurrence_total','seed_scan_job_completed',
      'seed_scan_progress_exhausted','raw_capture_pending_count',
      'seed_scan_job_pending','seed_scan_job_in_progress')
def public(value):
 if isinstance(value,dict):
  return {k:public(v) for k,v in value.items() if k not in
          ('last_request','snapshot','cookies','token','target_url','last_result')}
 if isinstance(value,list):return []
 return value
print(json.dumps({k:public(status[k]) for k in keys if k in status}))
"""


def read_progress(container_id, *, runner=run):
    output = runner(["exec", container_id, "python", "-c", STATUS_PROBE], timeout=25)
    return json.loads(output)


def progress_sample(status):
    """Fail closed on stale statistics, unknown contracts and access challenges."""
    if not isinstance(status, dict):
        raise ValueError("Invalid collection status")
    stats = status.get("statistics")
    if (
        not isinstance(stats, dict)
        or stats.get("valid") is not True
        or stats.get("stale") is not False
    ):
        raise ValueError("Collection statistics unavailable")
    age = stats.get("age_seconds")
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 120:
        raise ValueError("Collection statistics too old")
    if type(status.get("paused")) is not bool:
        raise ValueError("Missing pause state")
    scopes, recovery, solver = (
        status.get(k) for k in ("collection_scopes", "auth_recovery", "captcha_solver")
    )
    if not all(isinstance(v, dict) for v in (scopes, recovery, solver)):
        raise ValueError("Missing collection control state")
    if "active" not in recovery or type(solver.get("running")) is not bool:
        raise ValueError("Missing authentication state")
    for name in ("seed", "detail"):
        scope = scopes.get(name)
        if not isinstance(scope, dict) or type(scope.get("paused")) is not bool:
            raise ValueError("Missing collection scope")
    blocked = (
        status["paused"] or bool(recovery.get("active")) or bool(solver.get("running"))
    )
    for scope in scopes.values():
        if not isinstance(scope, dict):
            raise ValueError("Invalid collection scope")
        blocked = blocked or any(
            scope.get(k)
            for k in (
                "paused",
                "challenge_id",
                "manual_required",
                "manual_only",
                "node_solver_blocked",
            )
        )
    keys = (
        "captured_count",
        "seed_occurrence_total",
        "seed_scan_job_completed",
        "seed_scan_progress_exhausted",
        "raw_capture_pending_count",
        "seed_scan_job_pending",
        "seed_scan_job_in_progress",
    )
    values = [status.get(k) for k in keys]
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("Missing collection progress counts")
    return {
        "counters": values[:4],
        "eligible": not blocked and sum(values[4:]) > 0,
        "reason": "paused_or_authentication"
        if blocked
        else ("work_pending" if sum(values[4:]) else "idle"),
    }
