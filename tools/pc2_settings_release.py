"""Settings-aware release seam, invoked with the shared host lock already held."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import uuid

from .collection_control_lock import private_root
from .pc2_settings_model import inventory, literal_compose, render, workers
from .pc2_settings_runtime import SettingsRuntime, write_private


def browser_mounts(model):
    service = model["services"]["pc2-browser-solver"]
    mounts = {(m["source"], m["target"], not m.get("read_only", False)) for m in service.get("volumes", [])}
    for reference in service.get("secrets", []):
        reference = {"source": reference} if isinstance(reference, str) else reference
        source = reference["source"]
        definition = model.get("secrets", {}).get(source, {})
        path = definition.get("file")
        if not isinstance(path, str) or not path.startswith("/") or definition.get("external"):
            raise ValueError("Only resolved file-backed PC2 secrets are supported")
        target = reference.get("target") or source
        if not target.startswith("/"):
            target = "/run/secrets/" + target
        mounts.add((path, target, False))
    return mounts


def rebase(active, target, browser_only=False):
    if browser_only:
        result = deepcopy(active)
        result["services"]["pc2-browser-solver"] = deepcopy(target["services"]["pc2-browser-solver"])
        result["secrets"] = deepcopy(target.get("secrets", {}))
    else:
        key = active["services"]["pc2-analysis-1"]["environment"].get("OPENAI_API_KEY")
        result = render(target, inventory(active)["effective"], key)
        for name, service in workers(result).items():
            if name.startswith("pc2-analysis-"):
                service["environment"]["OPENAI_API_KEY"] = key or ""
    for name, service in result["services"].items():
        template = active["services"].get(name, active["services"].get(name.rsplit("-", 1)[0] + "-1"))
        if template is None or service.get("volumes", []) != template.get("volumes", []):
            raise ValueError("Release changes persistent mounts; requires a separate migration")
    if browser_mounts(active) != browser_mounts(result):
        raise ValueError("Release changes browser secret mounts; requires a separate migration")
    return result


class ReleaseRuntime:
    def __init__(self, runtime):
        self.runtime = runtime
        self.journal = runtime.root / "release-operation.json"

    def compose(self, compose_args, arguments):
        allowed = (["config", "--quiet"], ["ps"], ["ps", "pc2-browser-solver"],
                   ["up", "-d", "--remove-orphans"], ["up", "-d", "--no-deps", "pc2-browser-solver"])
        if arguments not in allowed:
            raise ValueError("Unsupported release Compose action")
        target = json.loads(self.runtime.run(["compose", "-p", "fapaifang-pc2", *compose_args, "config", "--format", "json"]))
        active = self.runtime.model()
        browser_only = "pc2-browser-solver" in arguments and arguments[0] == "up"
        after = rebase(active, target, browser_only)
        if arguments[0] == "ps":
            return self.runtime.run(["compose", "-p", "fapaifang-pc2", *compose_args, *arguments])
        if arguments[0] == "up":
            names = ["pc2-browser-solver"] if browser_only else sorted(after["services"])
            self.runtime.require_compose_safe(names)
            for name in names:
                image = self.runtime.run(["image", "inspect", "--format", "{{.Id}}", after["services"][name]["image"]]).strip()
                if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                    raise ValueError("Release image is not available locally")
                after["services"][name]["image"] = image
        directory = self.runtime.root / ("release-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        path = directory / "compose.json"
        write_private(path, literal_compose(after))
        self.runtime.compose(path, ["config", "--quiet"])
        if arguments[0] == "config":
            return "Settings-preserving release configuration validated"
        write_private(directory / "before.json", active)
        write_private(directory / "after.json", after)
        staged = directory / "journal.json"
        write_private(staged, {"directory": str(directory)})
        os.replace(staged, self.journal)
        self.runtime.compose(path, ["up", "-d", "--no-deps", "--no-build", "--pull", "never", *names])
        return "Settings-preserving release started; health confirmation required"

    def finish(self):
        if not self.journal.exists():
            raise ValueError("Release receipt is missing")
        directory = Path(json.loads(self.journal.read_text(encoding="utf-8"))["directory"])
        if directory.is_symlink() or directory.resolve(strict=True).parent != self.runtime.root or not directory.name.startswith("release-"):
            raise ValueError("Invalid release journal")
        after = json.loads((directory / "after.json").read_text(encoding="utf-8"))
        if not self.runtime.wait_ready(after):
            raise RuntimeError("Release workers are not healthy")
        browser = json.loads(self.runtime.run(["inspect", "fapaifang-pc2-browser-solver"]))[0]
        if (not browser["State"]["Running"] or browser["State"].get("Health", {}).get("Status") != "healthy"
                or after["services"]["pc2-browser-solver"]["image"] not in {browser["Image"], browser["Config"].get("Image")}):
            raise RuntimeError("Release browser is not healthy")
        expected = after["services"]["pc2-browser-solver"]
        env = dict(value.split("=", 1) for value in browser["Config"]["Env"])
        mounts = {(m["Source"], m["Destination"], m["RW"]) for m in browser["Mounts"]}
        if (any(env.get(key) != str(value) for key, value in expected.get("environment", {}).items())
                or mounts != browser_mounts(after)):
            raise RuntimeError("Release browser configuration drifted")
        staged = directory / "active.json"
        write_private(staged, after)
        os.replace(staged, self.runtime.active)
        self.journal.unlink()
        return "Release healthy; operator settings preserved"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--env-file", action="append", default=[], type=Path)
    parser.add_argument("action", choices=["compose", "finish"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    private_root(args.runtime_root)
    runtime = SettingsRuntime(args.runtime_root.resolve(), [])
    if not runtime.active.is_file():
        parser.error("Provisioned active settings are required")
    release = ReleaseRuntime(runtime)
    try:
        if args.action == "finish":
            print(release.finish())
        else:
            compose = []
            for path in args.env_file:
                compose.extend(["--env-file", str(path.resolve(strict=True))])
            compose.extend(["-f", str(args.compose_file.resolve(strict=True))])
            print(release.compose(compose, args.arguments))
    except Exception:
        # Compose errors can contain environment expansions; never echo them.
        parser.exit(1, "Settings-preserving release failed; inspect the private journal before recovery\n")


if __name__ == "__main__":
    main()
