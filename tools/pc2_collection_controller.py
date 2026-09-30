"""One explicitly enabled host controller for settings and engine restarts."""

import argparse
import os
import subprocess
import time
from pathlib import Path

from .collection_control_lock import operation_lock
from .controller_receipts import deliver_receipt
from .pc2_collection_progress_watchdog import CollectionProgressWatchdog
from .pc2_collection_watchdog import CollectionWatchdog
from .pc2_engine_controller import (
    ControllerError,
    EngineController,
    MailboxClient,
    validate_command,
)
from .pc2_settings_controller import SettingsClient, SettingsController
from .pc2_settings_runtime import SettingsRuntime, write_private


class RestartController:
    def __init__(self, client, engine, root):
        self.client, self.engine, self.root = client, engine, Path(root)
        self.journal = self.root / "restart-receipt.json"

    def persist(self, receipt):
        staged = self.root / "restart-receipt.new"
        if staged.exists():
            staged.unlink()
        write_private(staged, receipt)
        os.replace(staged, self.journal)

    def step(self):
        if self.journal.exists():
            deliver_receipt(self.client, self.journal)
            return
        self.engine.inspect()
        command = self.client.post("poll", {}).get("command")
        if command:
            command = validate_command(command)
            receipt = {
                "request_id": command["request_id"],
                "claim": command["claim"],
                "result": "controller_interrupted",
            }
            self.persist(receipt)
            receipt["result"] = self.engine.restart()
            self.persist(receipt)


def step(root, settings, restart, watchdog=None, progress_watchdog=None):
    with operation_lock(root):
        if (root / "release-operation.json").exists():
            raise ControllerError("Release result needs reconciliation")
        if (
            watchdog is not None
            and not settings.journal.exists()
            and not restart.journal.exists()
        ):
            if watchdog.step() == "restart_requested":
                return
        if (
            progress_watchdog is not None
            and not settings.journal.exists()
            and not restart.journal.exists()
        ):
            if progress_watchdog.step() == "restart_requested":
                return
        # An uncertain settings operation must not be followed by a restart.
        settings.step()
        if settings.journal.exists():
            return
        restart.step()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--compose-file", required=True, type=Path)
    parser.add_argument("--env-file", action="append", type=Path, default=[])
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run or os.name != "posix":
        parser.error("--run on the PC2 Linux host is required")
    compose = []
    for path in args.env_file:
        compose.extend(["--env-file", str(path.resolve(strict=True))])
    compose.extend(["-f", str(args.compose_file.resolve(strict=True))])
    runtime = SettingsRuntime(args.runtime_root.resolve(), compose)
    settings = SettingsController(
        SettingsClient(args.api_base, args.token_file, ca_file=args.ca_file), runtime
    )
    restart = RestartController(
        MailboxClient(args.api_base, args.token_file, ca_file=args.ca_file),
        EngineController(),
        runtime.root,
    )
    watchdog = CollectionWatchdog(runtime.root)
    progress_watchdog = CollectionProgressWatchdog(runtime.root)
    with operation_lock(runtime.root, name="controller.lock"):
        while True:
            try:
                step(runtime.root, settings, restart, watchdog, progress_watchdog)
            except (
                OSError,
                ValueError,
                RuntimeError,
                subprocess.SubprocessError,
                ControllerError,
            ):
                print(
                    "Collection controller unavailable; no operation replayed",
                    flush=True,
                )
            time.sleep(5)


if __name__ == "__main__":
    main()
