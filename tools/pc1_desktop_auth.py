"""Explicit human browser handoff. Never solves or bypasses a challenge."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import parse_qsl, quote, urlsplit
import urllib.request

from tools import taobao_inplace_auth_handoff as handoff
from tools.pc1_desktop_recovery import RecoveryClient, RecoveryError, recovery_phase
from tools.manual_auth_snapshot import completion_lock, publish_snapshot
from tools.desktop_runtime_config import load_runtime_environment
from tools.desktop_environment import environment_value
from src.project_environment import EnvironmentAliasConflict
from src.project_data_paths import resolve_project_data_root
from src.auth_recovery_codes import CHALLENGE_CHANGED_CODE

ROOT = Path(__file__).resolve().parents[1]


def target_identity(value):
    url = urlsplit(value)
    if url.scheme != "https" or url.username or url.password or url.port not in {None, 443}:
        raise RecoveryError("invalid_target")
    if not ((url.hostname == "sf.taobao.com" and url.path.startswith("/list/")) or
            (url.hostname == "sf-item.taobao.com" and re.fullmatch(r"/sf_item/\d+\.htm", url.path))):
        raise RecoveryError("invalid_target")
    query = tuple(sorted((key, value) for key, value in parse_qsl(url.query, keep_blank_values=True)
                         if key != "__captcha_solver_bg"))
    return url.hostname, url.path, query


def find_target(endpoint, url, target_id=""):
    expected = target_identity(url)
    for tab in handoff.taobao_login_health.list_cdp_targets(endpoint):
        if tab.get("type") != "page" or (target_id and tab.get("id") != target_id):
            continue
        try:
            if target_identity(str(tab.get("url") or "")) == expected:
                return str(tab["id"])
        except (ValueError, RecoveryError):
            continue
    raise RecoveryError("challenge_page_not_ready")


def open_challenge(url, endpoint, port, data_root, *, environment=None):
    environment = os.environ if environment is None else environment
    target_identity(url)
    profile = environment_value("CROW_AUTH_BROWSER_PROFILE_DIR", environment=environment, root=ROOT) or str(data_root / "chrome-cdp-profile-pc1-human-clean")
    browser_path = environment_value("CROW_AUTH_BROWSER_PATH", environment=environment, root=ROOT)
    try:
        previous_ids = {tab.get("id") for tab in handoff.taobao_login_health.list_cdp_targets(endpoint)}
    except (RuntimeError, OSError):
        previous_ids = set()
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts" / "start-taobao-cdp-browser.ps1"), "-Port", str(port),
               "-StartUrl", url, "-DataRoot", str(data_root), "-ProfileDir", profile,
               "-DebuggingAddress", "127.0.0.1", "-HumanAuthMode"]
    if browser_path:
        command += ["-BrowserPath", browser_path]
    result = subprocess.run(command, capture_output=True, timeout=75,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RecoveryError("browser_unavailable")
    try:
        selected = find_target(endpoint, url)
    except RecoveryError:
        opened = [tab for tab in handoff.taobao_login_health.list_cdp_targets(endpoint)
                  if tab.get("id") not in previous_ids and tab.get("type") == "page"
                  and (urlsplit(str(tab.get("url") or "")).hostname or "").endswith(".taobao.com")]
        if len(opened) == 1:
            selected = opened[0]["id"]  # Preserve this exact tab even during its login redirect.
        else:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request(endpoint + "/json/new?" + quote(url, safe=""), method="PUT")
            with opener.open(request, timeout=10) as response:
                selected = json.load(response).get("id")
    if not selected:
        raise RecoveryError("challenge_page_not_ready")
    return {"phase": "ready_for_human", "target_id": selected}


def complete_challenge(client, *, endpoint, output_path, request_id, challenge_id, url, target_id="", scope=""):
    with completion_lock(output_path):
        return _complete_locked(client, endpoint, output_path, request_id, challenge_id, url, target_id, scope)


def _complete_locked(client, endpoint, output_path, request_id, challenge_id, url, target_id, scope):
    target_identity(url)
    if not target_id:
        raise RecoveryError("challenge_page_not_ready")
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise RecoveryError("invalid_request")
    stage_request = {}
    if scope:
        host = target_identity(url)[0]
        if {"seed": "sf.taobao.com", "detail": "sf-item.taobao.com"}.get(scope) != host:
            raise RecoveryError("invalid_target")
        capabilities = client.call()["auth_recovery"]
        if capabilities.get("stage_auth_protocol") != 2:
            raise RecoveryError("stage_api_upgrade_required")
        if not capabilities.get("pc2_stage_auth_ready"):
            raise RecoveryError("pc2_stage_upgrade_required")
        stage_request = {"scope": scope, "target_url": url, "protocol_version": 2}
    start = client.call("/request", {"request_id": request_id, "challenge_id": challenge_id, **stage_request})
    if start.get("result"):
        last = start["result"]
        return recovery_phase({"last_result": last}, last["recovery_id"], scope=scope)
    recovery = start["recovery"]
    if scope and recovery.get("scope") != scope:
        raise RecoveryError("handoff_busy")
    recovery_id = recovery["recovery_id"]
    if start.get("existing_recovery") and not recovery.get("manual_request_id"):
        return {"phase": "pending_pc2", "code": "existing_recovery", "recovery_id": recovery_id}
    if recovery["status"] not in {"requested", "pc1_claimed"}:
        return recovery_phase({"active": recovery}, recovery_id, scope=scope)
    if recovery["status"] == "requested":
        client.call("/claim", {"recovery_id": recovery_id, "role": "pc1", "node_id": "pc1"})
    try:
        selected = find_target(endpoint, url, target_id)
    except (RuntimeError, OSError):
        return {"phase": "pending_human", "code": "challenge_page_not_ready", "recovery_id": recovery_id}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="desktop-auth-", suffix=".json", dir=output_path.parent)
    os.close(descriptor)
    candidate = Path(name)
    try:
        try:
            handoff.complete_inplace_auth(cdp_endpoint=endpoint, output_path=candidate,
                                         required_target_id=selected, allow_list_only=target_identity(url)[0] == "sf.taobao.com",
                                         **({"scope": scope, "target_url": url} if scope else {}))
        except RuntimeError:
            return {"phase": "pending_human", "code": "session_not_reusable", "recovery_id": recovery_id}
        snapshot = client.call()["auth_recovery"]
        current = snapshot.get("active") or {}
        if current.get("recovery_id") != recovery_id or current.get("status") != "pc1_claimed":
            return recovery_phase(snapshot, recovery_id, scope=scope)
        raw = candidate.read_bytes()
        count, digest = publish_snapshot(output_path, recovery_id, raw)
        client.call("/snapshot_ready", {"recovery_id": recovery_id, "sha256": digest,
                                       "cookie_count": count, "created_at_epoch": time.time()})
        return {"phase": "pending_pc2", "code": "pc2_receiving", "recovery_id": recovery_id}
    finally:
        candidate.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("open", "complete", "status"), required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--target-url", default="")
    parser.add_argument("--target-id", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--challenge-id", default="")
    parser.add_argument("--recovery-id", default="")
    parser.add_argument("--scope", choices=("seed", "detail"), default="")
    parser.add_argument("--peer-url", default="")
    parser.add_argument("--peer-challenge-id", default="")
    args = parser.parse_args(argv)
    try:
        environment = load_runtime_environment(ROOT)
        data_root = resolve_project_data_root(ROOT, env=environment)
        port = int(environment_value("CROW_AUTH_LOCAL_CDP_PORT", environment=environment, root=ROOT) or 9225)
        endpoint = f"http://127.0.0.1:{port}"
        if args.action == "open":
            result = open_challenge(args.target_url, endpoint, port, data_root, environment=environment)
        else:
            client = RecoveryClient(args.api_base, data_root, environment=environment)
            output = Path(environment_value("CROW_COOKIE_SNAPSHOT", environment=environment, root=ROOT) or data_root / "secrets" / "nodes" / "pc2" / "taobao-cookies.json")
            if args.peer_url or args.recovery_id.startswith("shared-auth-"):
                from tools.pc1_shared_auth import shared_challenge
                result = shared_challenge(client, output=output,
                                          request_id=args.recovery_id.removeprefix("shared-auth-") if args.action == "status" else args.request_id,
                                          endpoint=endpoint, scope=args.scope, url=args.target_url, target_id=args.target_id,
                                          challenge_id=args.challenge_id, peer_url=args.peer_url,
                                          peer_challenge_id=args.peer_challenge_id, status=args.action == "status")
            elif args.action == "status":
                result = recovery_phase(client.call()["auth_recovery"], args.recovery_id, scope=args.scope)
            else:
                result = complete_challenge(client, endpoint=endpoint, output_path=output, request_id=args.request_id,
                                            challenge_id=args.challenge_id, url=args.target_url, target_id=args.target_id, scope=args.scope)
    except EnvironmentAliasConflict:
        result = {"phase": "unavailable", "code": "runtime_config_invalid"}
    except RecoveryError as error:
        result = {"phase": "failed" if str(error) == CHALLENGE_CHANGED_CODE else "unavailable", "code": str(error)}
    except Exception:
        result = {"phase": "unavailable", "code": "handoff_unavailable"}
    print("CROW_AUTH_RESULT=" + json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
