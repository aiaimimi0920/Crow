"""One human snapshot, two serialized v2 stage handoffs, durable local receipts."""
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from tools.manual_auth_snapshot import completion_lock, publish_snapshot, snapshot_path, validate_snapshot
from tools.pc1_desktop_recovery import RecoveryError, recovery_phase
from src.auth_recovery_codes import CHALLENGE_CHANGED_CODE

MAX_AGE = 30 * 60


def _job_path(output, request_id):
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise RecoveryError("invalid_request")
    return output.parent / "desktop-auth" / f"shared-{request_id}.json"


def _save(path, job):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(job, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _response(job, phase="pending_pc2", code="shared_receiving"):
    results = {entry["scope"]: entry.get("result", {"phase": "pending_pc2"}) for entry in job["stages"]}
    return {"phase": phase, "code": code, "shared": True,
            "recovery_id": "shared-auth-" + job["request_id"], "stage_results": results}


def _capture(output, request_id, endpoint, scope, url, target_id):
    from tools.pc1_desktop_auth import find_target, handoff
    selected = find_target(endpoint, url, target_id)
    descriptor, name = tempfile.mkstemp(dir=output.parent, suffix=".json")
    os.close(descriptor)
    candidate = Path(name)
    try:
        try:
            handoff.complete_inplace_auth(cdp_endpoint=endpoint, output_path=candidate,
                                         required_target_id=selected, allow_list_only=scope == "seed",
                                         scope=scope, target_url=url)
        except RuntimeError as error:
            raise RecoveryError("session_not_reusable") from error
        count, digest = publish_snapshot(output, "auth-recovery-" + request_id, candidate.read_bytes())
        return {"sha256": digest, "cookie_count": count}
    finally:
        candidate.unlink(missing_ok=True)


def shared_challenge(client, *, output, request_id, endpoint="", scope="", url="",
                     target_id="", challenge_id="", peer_url="", peer_challenge_id="", status=False,
                     capture_snapshot=None):
    from tools.pc1_desktop_auth import target_identity
    path = _job_path(output, request_id)
    with completion_lock(output):
        if path.exists():
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["api"] != client.url:
                raise RecoveryError("api_not_configured")
        elif status:
            raise RecoveryError(CHALLENGE_CHANGED_CODE)
        else:
            if scope not in {"seed", "detail"} or not target_id:
                raise RecoveryError("challenge_page_not_ready")
            peer = "detail" if scope == "seed" else "seed"
            targets = [(scope, url, challenge_id), (peer, peer_url, peer_challenge_id)]
            for stage, target, _ in targets:
                if target_identity(target)[0] != {"seed": "sf.taobao.com", "detail": "sf-item.taobao.com"}[stage]:
                    raise RecoveryError("invalid_target")
            capabilities = client.call()["auth_recovery"]
            if capabilities.get("stage_auth_protocol") != 2:
                raise RecoveryError("stage_api_upgrade_required")
            if not capabilities.get("pc2_stage_auth_ready"):
                raise RecoveryError("pc2_stage_upgrade_required")
            if capture_snapshot is None:
                snapshot = _capture(output, request_id, endpoint, scope, url, target_id)
            else:
                count, digest = publish_snapshot(output, "auth-recovery-" + request_id, capture_snapshot())
                snapshot = {"sha256": digest, "cookie_count": count}
            job = {"request_id": request_id, "api": client.url, "created": time.time(),
                   "snapshot": snapshot, "stages": [
                       {"scope": stage, "target_url": target, "challenge_id": challenge,
                        "request_id": uuid.uuid5(uuid.UUID(request_id), stage).hex}
                       for stage, target, challenge in sorted(targets, key=lambda item: item[0] != "seed")]}
            _save(path, job)
        try:
            return _advance(client, output, path, job)
        except RecoveryError as error:
            if str(error) not in {"api_unavailable", "handoff_busy"}:
                raise
            return _response(job, code="shared_retry")


def _advance(client, output, path, job):
    snapshot = client.call()["auth_recovery"]
    active = snapshot.get("active") or {}
    # Resume an abandoned, unpublished desktop request using this human's fresh
    # snapshot. Keep its identity and ask NAS to revalidate the challenge first.
    if active.get("manual_request_id") and active.get("status") in {"requested", "pc1_claimed"}:
        for entry in job["stages"]:
            if (not entry.get("result") and not entry.get("recovery_id")
                    and entry["scope"] == active.get("scope")
                    and entry["challenge_id"] == active.get("challenge_id")):
                entry.update(request_id=active["manual_request_id"], target_url=active["target_url"])
                job["stages"].remove(entry)
                job["stages"].insert(0, entry)
                _save(path, job)
                break
    for entry in job["stages"]:
        if entry.get("result"):
            continue
        recovery_id = entry.get("recovery_id")
        if recovery_id:
            result = recovery_phase(snapshot, recovery_id, scope=entry["scope"])
            if result["phase"] == "pending_pc2":
                return _response(job)
            entry["result"] = result
            _save(path, job)
            continue
        if time.time() - job["created"] > MAX_AGE:
            entry["result"] = {"phase": "failed", "code": "shared_snapshot_expired"}
            _save(path, job)
            continue
        if active and active.get("manual_request_id") != entry["request_id"]:
            return _response(job, code="shared_queued")
        raw = snapshot_path(output, "auth-recovery-" + job["request_id"], job["snapshot"]["sha256"]).read_bytes()
        if validate_snapshot(raw)[1] != job["snapshot"]["sha256"]:
            raise RecoveryError("invalid_snapshot")
        try:
            start = client.call("/request", {key: entry[key] for key in
                                ("request_id", "scope", "target_url", "challenge_id")} | {"protocol_version": 2})
        except RecoveryError as error:
            if str(error) == "handoff_busy":
                return _response(job, code="shared_queued")
            if str(error) != CHALLENGE_CHANGED_CODE:
                raise
            entry["result"] = {"phase": "failed", "code": CHALLENGE_CHANGED_CODE}
            _save(path, job)
            continue
        if start.get("result"):
            result = start["result"]
            entry["recovery_id"] = result["recovery_id"]
            entry["result"] = recovery_phase({"last_result": result}, result["recovery_id"], scope=entry["scope"])
            _save(path, job)
            continue
        recovery = start["recovery"]
        if recovery.get("scope") != entry["scope"] or recovery.get("manual_request_id") != entry["request_id"]:
            return _response(job, code="shared_queued")
        recovery_id = recovery["recovery_id"]
        if recovery["status"] == "requested":
            client.call("/claim", {"recovery_id": recovery_id, "role": "pc1", "node_id": "pc1"})
        if recovery["status"] in {"requested", "pc1_claimed"}:
            count, digest = publish_snapshot(output, recovery_id, raw)
            client.call("/snapshot_ready", {"recovery_id": recovery_id, "sha256": digest,
                                           "cookie_count": count, "created_at_epoch": job["created"]})
        # If the acknowledgement was lost, retry uses the same request and file.
        entry["recovery_id"] = recovery_id
        _save(path, job)
        return _response(job)
    succeeded = all(entry["result"]["phase"] == "succeeded" for entry in job["stages"])
    return _response(job, "succeeded" if succeeded else "failed",
                     "shared_succeeded" if succeeded else "shared_partial")
