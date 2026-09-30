"""Exercise the installed launcher boundary without a browser or network calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get("SystemRoot", "")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows desktop launcher")


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle with spaces"
    (root / "scripts").mkdir(parents=True)
    (root / "tools").mkdir()
    shutil.copyfile(ROOT / "scripts/desktop-auth-challenge.ps1", root / "scripts/desktop-auth-challenge.ps1")
    shutil.copyfile(ROOT / "scripts/project-data-root.ps1", root / "scripts/project-data-root.ps1")
    shutil.copyfile(ROOT / "scripts/project-environment.ps1", root / "scripts/project-environment.ps1")
    (root / "tools/__init__.py").write_text("", encoding="utf-8")
    (root / "tools/pc1_desktop_auth.py").write_text(
        "import json, os, sys\n"
        "print('CROW_AUTH_RESULT=' + json.dumps({'phase': 'pending_human', "
        "'cwd': os.getcwd(), 'python': sys.executable, 'args': sys.argv[1:], "
        "'utf8': os.environ.get('PYTHONIOENCODING')}))\n",
        encoding="utf-8",
    )
    write_config(root, sys.executable)
    return root


def write_config(root, python):
    (root / "crow-desktop.runtime.json").write_text(json.dumps({
        "version": 1, "environment": {"FAPAI_DESKTOP_PYTHON_PATH": python},
    }), encoding="utf-8")


def launch(root, *, environ=None, cwd=None, extra=()):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("FAPAI_", "CROW_", "PYTHON"))}
    environment.update(PATH=str(POWERSHELL.parent.parent.parent), PYTHONDONTWRITEBYTECODE="1")
    environment.update(environ or {})
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(root / "scripts/desktop-auth-challenge.ps1"), "-Action", "status", "-ApiBase", "invalid", *extra],
        cwd=cwd or root.parent, env=environment, capture_output=True, timeout=30,
    )


def result(process):
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    lines = process.stdout.decode("utf-8").splitlines()
    return json.loads(next(line.removeprefix("CROW_AUTH_RESULT=")
                           for line in lines if line.startswith("CROW_AUTH_RESULT=")))


def test_configured_interpreter_works_without_python_on_path_and_ignores_cwd_modules(bundle, tmp_path):
    wrong = tmp_path / "unrelated"
    (wrong / "tools").mkdir(parents=True)
    (wrong / "tools/__init__.py").write_text("raise RuntimeError('wrong module')", encoding="utf-8")
    payload = result(launch(bundle, cwd=wrong, environ={"PYTHONPATH": str(wrong)}))
    assert Path(payload["cwd"]) == bundle
    assert Path(payload["python"]) == Path(sys.executable)
    assert payload["utf8"] == "utf-8"


def test_explicit_interpreter_environment_wins_over_bundle_default(bundle):
    write_config(bundle, str(bundle / "missing.exe"))
    payload = result(launch(bundle, environ={"FAPAI_DESKTOP_PYTHON_PATH": sys.executable}))
    assert Path(payload["python"]) == Path(sys.executable)


def test_legacy_bundle_can_still_resolve_python_from_path(bundle):
    (bundle / "crow-desktop.runtime.json").unlink()
    payload = result(launch(bundle, environ={"PATH": str(Path(sys.executable).parent)}))
    assert payload["phase"] == "pending_human"


@pytest.mark.parametrize("python", ["missing.exe", "python", 123, {"secret": "do-not-log"}])
def test_invalid_configured_python_fails_closed_without_path_fallback(bundle, python):
    write_config(bundle, python)
    process = launch(bundle, environ={"PATH": str(Path(sys.executable).parent)})
    assert process.returncode != 0
    assert b"CROW_AUTH_RESULT=" not in process.stdout
    receipt = (bundle / "CrowData/desktop-auth/last-launch-failure.json").read_text(encoding="utf-8")
    assert json.loads(receipt)["failure"] in {"runtime_config_invalid", "python_unavailable"}
    assert "do-not-log" not in receipt


def test_malformed_config_never_prints_its_contents(bundle):
    (bundle / "crow-desktop.runtime.json").write_text('secret-do-not-log{', encoding="utf-8")
    process = launch(bundle)
    assert process.returncode != 0
    assert b"secret-do-not-log" not in process.stdout + process.stderr


def test_helper_exit_is_recorded_without_stderr_arguments_or_credentials(bundle):
    (bundle / "tools/pc1_desktop_auth.py").write_text(
        "import sys\nprint('secret-do-not-log', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8",
    )
    process = launch(bundle, extra=("-TargetUrl", "https://example.invalid/?secret=do-not-log"))
    assert process.returncode == 7
    receipt = (bundle / "CrowData/desktop-auth/last-launch-failure.json").read_text(encoding="utf-8")
    assert json.loads(receipt)["exit_code"] == 7
    assert json.loads(receipt)["failure"] == "python_exit"
    assert "do-not-log" not in receipt


def test_stderr_warning_is_not_a_powershell_terminating_error(bundle):
    helper = bundle / "tools/pc1_desktop_auth.py"
    helper.write_text("import sys\nprint('fixture warning', file=sys.stderr)\n" + helper.read_text(), encoding="utf-8")
    assert result(launch(bundle))["phase"] == "pending_human"


def test_query_arguments_remain_single_values(bundle):
    url = "https://sf.taobao.com/list/123.htm?city=hello%20world&item=123"
    payload = result(launch(bundle, extra=("-TargetUrl", url, "-TargetId", "fixture-target")))
    assert payload["args"] == ["--action", "status", "--api-base", "invalid",
                               "--target-url", url, "--target-id", "fixture-target"]


def test_call_operator_invocation_reports_the_helper_exit_code(bundle):
    # Operators and other scripts invoke the wrapper with "& script"; the helper's
    # exit code must still be observed instead of defaulting to python_launch.
    script = str(bundle / "scripts/desktop-auth-challenge.ps1").replace("'", "''")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("FAPAI_", "CROW_", "PYTHON"))}
    environment.update(PATH=str(POWERSHELL.parent.parent.parent), PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         f"& '{script}' -Action status -ApiBase invalid; exit $LASTEXITCODE"],
        cwd=bundle.parent, env=environment, capture_output=True, timeout=30,
    )
    assert result(process)["phase"] == "pending_human"
    assert not (bundle / "CrowData/desktop-auth/last-launch-failure.json").exists()
