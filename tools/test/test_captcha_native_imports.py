"""Captcha imports and platform fakes do not mutate unrelated process state."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.captcha_solver import CaptchaSolver
from tools.test.captcha_solver_test_context import set_solver_platform


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_platform_injection_leaves_the_host_filesystem_available(
    monkeypatch, tmp_path, platform
):
    host_platform = os.name
    set_solver_platform(monkeypatch, platform)
    solver = CaptchaSolver()
    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "native")
    assert solver._native_os_input_enabled() is (platform == "nt")
    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "uinput")
    assert solver._uinput_os_input_enabled() is (platform != "nt")
    assert os.name == host_platform
    assert Path(tmp_path).is_dir()


def test_captcha_import_preserves_host_stream_configuration(tmp_path):
    code = "\n".join(
        [
            "import io, sys, types",
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})",
            "changes = []",
            "streams = sys.stdout, sys.stderr",
            "class HostStream(io.StringIO):",
            "    def reconfigure(self, **kwargs):",
            "        changes.append(kwargs)",
            "sys.stdout = HostStream()",
            "sys.stderr = HostStream()",
            "try:",
            "    from src import captcha_solver",
            "finally:",
            "    sys.stdout, sys.stderr = streams",
            "assert type(captcha_solver) is types.ModuleType",
            "assert changes == [], changes",
            "assert 'src.server_context' not in sys.modules",
            "assert 'src.server' not in sys.modules",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
