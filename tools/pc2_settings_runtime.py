"""Opt-in bounded Compose reconciliation. Never changes browser, images or mounts."""
import json
import os
import subprocess
import time
from pathlib import Path

from .pc2_container_inventory import (
    BROWSER,
    canonical_containers,
    require_compose_safe_inventory,
)
from .pc2_settings_model import WORKER, inventory, literal_compose, render, workers

PROJECT = "fapaifang-pc2"


def run(arguments, timeout=60):
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=True, timeout=timeout).stdout


def write_private(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())


class SettingsRuntime:
    def __init__(self, root, compose_args, *, runner=run, sleep=time.sleep, clock=time.monotonic, docker_api=None):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and (self.root.is_symlink() or self.root.stat().st_uid != os.geteuid() or self.root.stat().st_mode & 0o077):
            raise ValueError("Settings runtime root must be owner-only")
        self.run, self.sleep, self.clock = runner, sleep, clock
        self.compose_args = compose_args
        self.active = self.root / "active.json"
        self.docker_api = docker_api

    def model(self):
        if self.active.exists():
            return json.loads(self.active.read_text(encoding="utf-8"))
        return json.loads(self.run(["compose", "-p", PROJECT, *self.compose_args, "config", "--format", "json"]))

    def container_rows(self):
        ids = self.run(["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT]).split()
        return json.loads(self.run(["inspect", *ids])) if ids else []

    def inspect(self):
        return {service: row for service, row in canonical_containers(self.container_rows()).items() if service != BROWSER}

    def require_compose_safe(self, services):
        if services:
            require_compose_safe_inventory(self.container_rows(), services)

    @staticmethod
    def matches(model, rows, *, healthy):
        expected = workers(model)
        if any(name not in expected and row["State"]["Running"] for name, row in rows.items()):
            return False
        for name, service in expected.items():
            row = rows.get(name)
            if service.get("container_name") != "fapaifang-" + name:
                return False
            if any(mount.get("type") != "bind" for mount in service.get("volumes", [])):
                return False
            if not row or not row["State"]["Running"]:
                return False
            if healthy and row["State"].get("Health", {}).get("Status") != "healthy":
                return False
            if service["image"] not in (row["Image"], row["Config"].get("Image")):
                return False
            env = dict(value.split("=", 1) for value in row["Config"]["Env"])
            if any(env.get(key) != str(value) for key, value in service["environment"].items()):
                return False
            expected_mounts = {(mount["source"], mount["target"], not mount.get("read_only", False))
                               for mount in service.get("volumes", []) if mount.get("type") == "bind"}
            if any(mount["Type"] != "bind" for mount in row["Mounts"]):
                return False
            actual_mounts = {(mount["Source"], mount["Destination"], mount["RW"]) for mount in row["Mounts"]}
            if expected_mounts != actual_mounts:
                return False
        return True

    def snapshot(self):
        model = self.model()
        if not self.matches(model, self.inspect(), healthy=False):
            raise ValueError("Live settings drift from provisioned Compose; refusing to overwrite")
        return inventory(model)

    def wait_ready(self, model):
        deadline = self.clock() + 300
        while self.clock() < deadline:
            if self.matches(model, self.inspect(), healthy=True):
                return True
            self.sleep(5)
        return False

    def compose(self, path, args):
        if args and args[0] == "up":
            names = [name for name in args[1:] if name == BROWSER or WORKER.fullmatch(name)]
            if not names:
                raise ValueError("Compose recreation requires explicit collection services")
            self.require_compose_safe(names)
        return self.run(["compose", "-p", PROJECT, "-f", str(path), *args], timeout=180)

    def apply(self, request):
        before = self.model()
        rows = self.inspect()
        if not self.matches(before, rows, healthy=False):
            return "rejected"
        if inventory(before)["effective"] != request["previous"]:
            return "rejected"
        for name, service in workers(before).items():
            service["image"] = rows[name]["Image"]
        after = render(before, request["config"], request["api_key"])
        # Pin every worker to its existing stage image, never pull mutable tags.
        for name, service in workers(after).items():
            template = name if name in workers(before) else name.rsplit("-", 1)[0] + "-1"
            service["image"] = rows[template]["Image"]
        old, new = workers(before), workers(after)
        changed = sorted(name for name in new if name not in old or new[name] != old[name])
        removed = sorted(set(old) - set(new))
        from .pc2_settings_ai_runtime import ai_only, apply_ai
        exact_ai = ai_only(before, after, changed, removed)
        try:
            if not exact_ai:
                self.require_compose_safe(set(changed) | set(removed))
        except ValueError:
            return "rejected"
        directory = self.root / request["request_id"]
        directory.mkdir(mode=0o700, exist_ok=False)
        old_path, new_path = directory / "before.json", directory / "after.json"
        write_private(old_path, literal_compose(before))
        write_private(new_path, literal_compose(after))
        if exact_ai:
            return apply_ai(self, before, after, rows, changed, directory, write_private)
        self.compose(old_path, ["config", "--quiet"])
        self.compose(new_path, ["config", "--quiet"])
        attempted = False
        try:
            attempted = True
            if removed:
                self.run(["stop", "--time", "30", *(rows[name]["Id"] for name in removed)], timeout=120)
            if changed:
                self.compose(new_path, ["up", "-d", "--no-deps", "--no-build", *changed])
            if not self.wait_ready(after):
                raise RuntimeError("Settings readiness failed")
            staged = directory / "active.json"
            write_private(staged, after)
            os.replace(staged, self.active)
            return "applied"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            if not attempted:
                return "rejected"
            try:
                current = self.inspect()
                added = [current[name]["Id"] for name in set(new) - set(old) if name in current]
                if added:
                    self.run(["stop", "--time", "30", *added], timeout=120)
                restore = sorted(set(removed) | (set(changed) & set(old)))
                if restore:
                    self.compose(old_path, ["up", "-d", "--no-deps", "--no-build", *restore])
                if not self.wait_ready(before):
                    return "interrupted"
                restored = directory / "active.before.json"
                write_private(restored, before)
                os.replace(restored, self.active)
                return "rolled_back"
            except (OSError, ValueError, subprocess.SubprocessError):
                return "interrupted"
