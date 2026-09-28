"""Verify the GUI-subsystem launcher preserves task results without a console."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows task launcher")


def pythonw():
    path = Path(sys.executable).with_name("pythonw.exe")
    assert path.is_file()
    return str(path)


@pytest.mark.parametrize("exit_code", [0, 23])
def test_gui_launcher_has_no_console_and_preserves_child_exit(tmp_path, exit_code):
    status = tmp_path / "status with spaces.json"
    proof = tmp_path / "child with spaces.json"
    code = (
        "import ctypes,json,pathlib,sys;"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({"
        "'console':ctypes.windll.kernel32.GetConsoleWindow(),'argument':sys.argv[2]}));"
        "print('synthetic-private-output');sys.exit(int(sys.argv[3]))"
    )
    result = subprocess.run(
        [
            pythonw(),
            "-I",
            str(ROOT / "tools/background_task_launcher.py"),
            "--status-path",
            str(status),
            "--",
            sys.executable,
            "-c",
            code,
            str(proof),
            "argument with spaces",
            str(exit_code),
        ],
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == exit_code
    assert json.loads(proof.read_text()) == {
        "console": 0,
        "argument": "argument with spaces",
    }
    recorded = json.loads(status.read_text())
    assert recorded["phase"] == "finished"
    assert recorded["exit_code"] == exit_code
    assert recorded["child_pid"] != recorded["pid"]
    assert "synthetic-private-output" not in status.read_text()
    assert not result.stdout and not result.stderr


def test_launch_failure_is_observable_without_raw_command_output(tmp_path):
    status = tmp_path / "status.json"
    result = subprocess.run(
        [
            pythonw(),
            "-I",
            str(ROOT / "tools/background_task_launcher.py"),
            "--status-path",
            str(status),
            "--",
            str(tmp_path / "missing.exe"),
        ],
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 1
    recorded = json.loads(status.read_text())
    assert recorded["phase"] == "launch_failed"
    assert recorded["error_type"] == "FileNotFoundError"
    assert "missing.exe" not in status.read_text()


def test_registration_defaults_to_gui_launcher_without_creating_a_task(tmp_path):
    registrar = str(ROOT / "scripts/register-pc1-nas-auth-recovery-task.ps1").replace(
        "'", "''"
    )
    python = sys.executable.replace("'", "''")
    command = r"""
$ErrorActionPreference='Stop'
function New-ScheduledTaskAction { param($Execute,$Argument,$WorkingDirectory)
    $script:action=@{execute=$Execute;arguments=$Argument;cwd=$WorkingDirectory};return $script:action }
function New-ScheduledTaskTrigger { return @{} }
function New-ScheduledTaskPrincipal { return @{} }
function New-ScheduledTaskSettingsSet { return @{} }
function New-ScheduledTask { return @{} }
function Register-ScheduledTask { }
function Enable-ScheduledTask { }
function Get-ScheduledTask { $script:action|ConvertTo-Json -Compress }
& '__REGISTRAR__' -ApiBase https://nas.example -Python '__PYTHON__'
""".replace("__REGISTRAR__", registrar).replace("__PYTHON__", python)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=25,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=tmp_path,
    )
    action = json.loads(result.stdout)
    assert Path(action["execute"]).name.lower() == "pythonw.exe"
    assert "background_task_launcher.py" in action["arguments"]
    assert "--status-path" in action["arguments"]
    assert "watch-pc1-nas-auth-recovery.ps1" in action["arguments"]
    assert "powershell.exe" in action["arguments"]
