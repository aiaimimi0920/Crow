"""Test the real installer payload, never importing helpers from the checkout."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from tools.test.test_desktop_auth_launcher import launch, result, write_config


ROOT = Path(__file__).resolve().parents[2]


def copy_declared_bundle(destination):
    script = (ROOT / "scripts/deploy-collector-desktop-local.ps1").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"foreach \(\$relativePath in @\(([^)]*)\)\) \{\s*Copy-BundleFile", script
    )
    assert match, "Installer payload declaration must remain testable"
    names = re.findall(r'"([^"\n]+\.(?:py|ps1))"', match[1])
    assert names and len(names) == len(set(names))
    for name in names:
        relative = Path(*name.split("\\"))
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return destination


@pytest.mark.parametrize("action", ["status", "open", "complete"])
def test_real_auth_payload_is_importable_and_handles_offline_request_in_isolation(
    tmp_path, action
):
    bundle = copy_declared_bundle(tmp_path / "installed bundle")
    probe = (
        "import pathlib, sys\n"
        "root = pathlib.Path(sys.argv[1]).resolve()\n"
        "sys.path.insert(0, str(root))\n"
        "from tools import pc1_desktop_auth as auth\n"
        "for name, module in list(sys.modules.items()):\n"
        "    if name.startswith(('tools.', 'src.')) and getattr(module, '__file__', None):\n"
        "        assert pathlib.Path(module.__file__).resolve().is_relative_to(root), name\n"
        "raise SystemExit(auth.main(['--action', sys.argv[2], '--api-base', 'invalid', '--target-url', 'invalid']))\n"
    )
    process = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(bundle), action],
        cwd=tmp_path,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("FAPAI_", "CROW_"))
        },
        capture_output=True,
        timeout=30,
    )
    payload = result(process)
    assert payload == {
        "phase": "unavailable",
        "code": "invalid_target" if action == "open" else "api_not_configured",
    }


def test_real_auth_payload_declares_its_lightweight_target_adapter(tmp_path):
    bundle = copy_declared_bundle(tmp_path / "installed bundle")
    assert (bundle / "src/collection/adapters/taobao_auth_target.py").is_file()


def test_real_browser_launcher_has_its_dot_sourced_modules_in_the_payload(tmp_path):
    bundle = copy_declared_bundle(tmp_path)
    entry = bundle / "scripts/start-taobao-cdp-browser.ps1"
    names = re.findall(
        r'\. \(Join-Path \$moduleRoot "([^"]+\.ps1)"\)',
        entry.read_text(encoding="utf-8"),
    )
    assert names
    for name in names:
        assert (entry.with_suffix("") / name).is_file(), name


@pytest.mark.skipif(os.name != "nt", reason="Windows installed launcher")
def test_real_installed_launcher_and_modules_work_without_checkout_or_python_path(
    tmp_path,
):
    bundle = copy_declared_bundle(tmp_path / "installed bundle")
    write_config(bundle, sys.executable)
    payload = result(launch(bundle))
    assert payload == {"phase": "unavailable", "code": "api_not_configured"}
    assert not (bundle / "CrowData/desktop-auth/last-launch-failure.json").exists()
