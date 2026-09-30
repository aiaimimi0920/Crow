"""Explicit opt-in settings controller. Development tests must use fake Docker/API."""
from src.project_data_paths import resolve_project_data_root

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error

from src.collection_engine_restart import identifier
from src.collection_settings_schema import PREFIX, validate, validate_key
from .pc2_engine_controller import ControllerError, MailboxClient
from .pc2_settings_runtime import SettingsRuntime, write_private
from .collection_control_lock import operation_lock
from .controller_receipts import deliver_receipt


class SettingsClient(MailboxClient):
    def __init__(self, api_base, token_file, *, ca_file=None):
        # No insecure-HTTP override for configuration or secret-bearing traffic.
        super().__init__(api_base, token_file, ca_file=ca_file)
        self.url = self.url.rsplit("/api/", 1)[0] + PREFIX


def validate_command(value):
    if not isinstance(value, dict) or set(value) != {"request_id", "revision", "claim", "config", "previous", "api_key"}:
        raise ValueError("Invalid settings command")
    identifier(value["request_id"])
    if type(value["revision"]) is not int or value["revision"] < 1:
        raise ValueError("Invalid revision")
    if not isinstance(value["claim"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["claim"]):
        raise ValueError("Invalid settings claim")
    validate(value["config"])
    validate(value["previous"])
    validate_key(value["api_key"])
    return value


class SettingsController:
    def __init__(self, client, runtime):
        self.client, self.runtime = client, runtime
        self.journal = runtime.root / "pending-receipt.json"

    def persist(self, receipt):
        staged = self.runtime.root / "pending-receipt.new"
        # A leftover staging file was never committed; do not treat it as a command.
        if staged.exists():
            staged.unlink()
        write_private(staged, receipt)
        os.replace(staged, self.journal)

    def step(self):
        if self.journal.exists():
            deliver_receipt(self.client, self.journal)
            return
        snapshot = self.runtime.snapshot()
        command = self.client.post("poll", snapshot).get("command")
        if not command:
            return
        command = validate_command(command)
        receipt = {"request_id": command["request_id"], "claim": command["claim"],
                   "result": "interrupted", "effective": None, "api_key_configured": False}
        # Persist uncertainty before any Docker mutation. A crash never replays the apply.
        self.persist(receipt)
        try:
            result = self.runtime.apply(command)
            if result != "interrupted":
                snapshot = self.runtime.snapshot()
                receipt.update(result=result, **snapshot)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            pass
        self.persist(receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True, help="HTTPS or protected loopback tunnel origin")
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--compose-file", required=True, type=Path)
    parser.add_argument("--env-file", action="append", type=Path, default=[])
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.runtime_root is None:
        args.runtime_root = resolve_project_data_root(Path(__file__).resolve().parents[1]) / "settings-controller"
    if not args.run:
        parser.error("--run is required; this enables remote configuration and container recreation")
    if os.name != "posix":
        parser.error("The live settings controller is supported only on the PC2 Linux host")
    compose_args = []
    for path in args.env_file:
        compose_args.extend(["--env-file", str(path.resolve(strict=True))])
    compose_args.extend(["-f", str(args.compose_file.resolve(strict=True))])
    runtime = SettingsRuntime(args.runtime_root.resolve(), compose_args)
    controller = SettingsController(SettingsClient(args.api_base, args.token_file, ca_file=args.ca_file), runtime)
    with operation_lock(runtime.root, name="controller.lock"):
        while True:
            try:
                with operation_lock(runtime.root):
                    if (runtime.root / "release-operation.json").exists():
                        raise ControllerError("Release result needs reconciliation")
                    controller.step()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, ControllerError):
                print("Settings controller unavailable; no apply replayed", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
