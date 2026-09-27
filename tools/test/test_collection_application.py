"""Exercise the production composition in fresh processes with real storage."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("source", ["catalog_x", "taobao_sf"])
def test_collection_api_start_accept_and_stop_without_postprocessing(tmp_path, source):
    probe = Path(__file__).with_name("collection_application_probe.py")
    result = subprocess.run(
        [sys.executable, str(probe), str(tmp_path), source],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=35,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert (
        "collection API: seed, HTML, storage, workers stopped; postprocessing absent"
        in result.stdout
    )
