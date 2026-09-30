"""Opt-in PC2 host controller; only restarts existing collection containers.

Never run this helper as part of development tests. Tests inject a fake runner.
The browser solver, Docker daemon, NAS, data volumes and images are not mutated.
"""

from __future__ import annotations

from src.project_data_paths import resolve_project_data_root

import argparse
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor

from tools.collection_control_lock import operation_lock
from tools.pc2_settings_model import WORKER, STAGES
from tools.pc2_container_inventory import canonical_containers, BROWSER

PROJECT = "fapaifang-pc2"


class ControllerError(Exception):
    pass


def run_docker(arguments: list[str], *, timeout: int):
    return subprocess.run(["docker", *arguments], check=True, capture_output=True, text=True, timeout=timeout)


class EngineController:
    def __init__(self, *, run=run_docker, sleep=time.sleep, clock=time.monotonic):
        self.run, self.sleep, self.clock = run, sleep, clock

    def inspect(self):
        ids = self.run(["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT], timeout=20).stdout.split()
        if not ids:
            raise ControllerError("Collection containers are missing")
        output = self.run(["inspect", *ids], timeout=20)
        rows = json.loads(output.stdout)
        try:
            canonical = canonical_containers(rows)
        except ValueError as error:
            raise ControllerError(str(error)) from error
        by_service = {service: row for service, row in canonical.items()
                      if service != BROWSER and row.get("State", {}).get("Running")}
        for role in STAGES.values():
            names = {name for name in by_service if name.startswith("pc2-" + role + "-")}
            if not names or names != {f"pc2-{role}-{i}" for i in range(1, len(names) + 1)}:
                raise ControllerError("Active worker identities must be contiguous")
        if len(by_service) > 16 or sum(name.startswith("pc2-seed-") for name in by_service) > 2:
            raise ControllerError("Worker count exceeds collection limits")
        return by_service

    def restart(self):
        attempted = False
        try:
            before = self.inspect()
            ids = [before[service]["Id"] for service in sorted(before)]
            attempted = True
            # Older Docker clients restart a multi-ID list serially. Eight
            # 30-second stops exceeded the old 120-second batch deadline.
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = [pool.submit(self.run, ["restart", "--time", "30", identity], timeout=60)
                           for identity in ids]
                for result in results:
                    result.result()
            deadline = self.clock() + 240
            while self.clock() < deadline:
                after = self.inspect()
                if set(after) != set(before):
                    return "controller_interrupted"
                ready = True
                for service in before:
                    row, old = after[service], before[service]
                    state = row.get("State", {})
                    if row["Id"] != old["Id"]:
                        return "controller_interrupted"
                    ready = ready and bool(state.get("Running") and state.get("Health", {}).get("Status") == "healthy"
                                           and state.get("StartedAt") and state.get("StartedAt") != old.get("State", {}).get("StartedAt"))
                if ready:
                    return "workers_ready"
                self.sleep(5)
            return "health_timeout"
        except subprocess.TimeoutExpired:
            return "controller_interrupted"
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError, ControllerError):
            return "controller_interrupted" if attempted else "restart_failed"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ControllerError("Controller API redirects are not allowed")


class MailboxClient:
    def __init__(self, api_base: str, token_file: Path, *, allow_insecure_http=False, ca_file=None):
        parsed = urllib.parse.urlsplit(api_base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ControllerError("Use an HTTP(S) API origin without embedded credentials")
        if parsed.path not in {"", "/", "/api", "/api/"}:
            raise ControllerError("API base must be the origin or end in /api")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and not allow_insecure_http:
            raise ControllerError("Remote HTTP requires explicit --allow-insecure-http; prefer HTTPS or a tunnel")
        self.url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/collection/control/restart", "", ""))
        self.token_file = token_file
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def post(self, action: str, body: dict):
        if action not in {"poll", "result", "apply"}:
            raise ControllerError("Unsupported controller action")
        return self.request("/" + action, body)

    def get(self):
        return self.request("", None)

    def request(self, suffix, body):
        token = self.token_file.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", token):
            raise ControllerError("Controller token file is invalid")
        raw = None if body is None else json.dumps(body).encode()
        if raw is not None and len(raw) > 16384:
            raise ControllerError("Controller request is too large")
        request = urllib.request.Request(self.url + suffix, data=raw, method="GET" if body is None else "POST",
                                         headers={"Content-Type": "application/json", "X-FAPAI-Control-Token": token})
        with self.opener.open(request, timeout=20) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ControllerError("Controller response is too large")
            payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ControllerError("Mailbox rejected the request")
        return payload


def validate_command(command: object) -> dict:
    if not isinstance(command, dict) or set(command) != {"request_id", "claim", "action"}:
        raise ControllerError("Invalid restart command fields")
    if command["action"] != "restart_collection_workers":
        raise ControllerError("Unsupported command")
    if not isinstance(command["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", command["request_id"]):
        raise ControllerError("Invalid restart request ID")
    if not isinstance(command["claim"], str) or not re.fullmatch(r"[a-f0-9]{64}", command["claim"]):
        raise ControllerError("Invalid restart claim")
    return command


def run_loop(client, controller, *, sleep=time.sleep, runtime_root=None):
    receipt = None
    while True:
        try:
            with operation_lock(runtime_root) if runtime_root is not None else nullcontext():
                if runtime_root is not None and (Path(runtime_root) / "release-operation.json").exists():
                    raise ControllerError("Release result needs reconciliation")
                if receipt is not None:
                    client.post("result", receipt)
                    print(f"Restart {receipt['request_id']}: {receipt['result']}", flush=True)
                    receipt = None
                controller.inspect()
                command = client.post("poll", {}).get("command")
                if command:
                    command = validate_command(command)
                    receipt = {"request_id": command["request_id"], "claim": command["claim"], "result": controller.restart()}
                    continue
        except urllib.error.HTTPError as error:
            # A terminal stale claim must not prevent later explicit operator requests.
            if error.code == 409:
                receipt = None
            print(f"Restart controller API unavailable (HTTP {error.code})", flush=True)
        except (OSError, ValueError, subprocess.SubprocessError, ControllerError):
            print("Restart controller unavailable; no command replayed", flush=True)
        sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--run", action="store_true", help="Explicitly enable polling and remote restart execution")
    parser.add_argument("--allow-insecure-http", action="store_true", help="Allow tokens over plaintext HTTP on an explicitly trusted isolated LAN")
    args = parser.parse_args()
    if args.runtime_root is None:
        args.runtime_root = Path(os.getenv("FAPAI_COLLECTION_CONTROL_ROOT") or resolve_project_data_root(Path(__file__).resolve().parents[1]) / "settings-controller")
    if not args.run:
        parser.error("--run is required; starting this controller enables remote engine restarts")
    run_loop(MailboxClient(args.api_base, args.token_file, allow_insecure_http=args.allow_insecure_http, ca_file=args.ca_file), EngineController(), runtime_root=args.runtime_root)


if __name__ == "__main__":
    main()
