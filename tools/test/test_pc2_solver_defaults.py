"""Runtime defaults and installation overrides do not depend on checkout names."""

import json
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("configured", [False, True])
def test_pc2_solver_does_not_embed_remote_api_topology(tmp_path, configured):
    env = dict(os.environ)
    for name in (
        "FAPAI_API_BASE_URL",
        "FAPAI_CDP_ENDPOINT",
        "FAPAI_LOCAL_SOLVER_POLL_SECONDS",
    ):
        env.pop(name, None)
    expected = ["http://127.0.0.1:8001/api", "http://127.0.0.1:9223", 5]
    if configured:
        expected = ["https://crow.example/api", "http://pc2.example:9224", 7]
        env.update(
            {
                "FAPAI_API_BASE_URL": expected[0],
                "FAPAI_CDP_ENDPOINT": expected[1],
                "FAPAI_LOCAL_SOLVER_POLL_SECONDS": str(expected[2]),
            }
        )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from tools import pc2_solver_config as config; "
            "print(json.dumps([config.DEFAULT_API_BASE_URL, "
            "config.DEFAULT_CDP_ENDPOINT, config.DEFAULT_POLL_SECONDS]))",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == expected
