from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("source", ["catalog_x", "taobao_sf"])
def test_seed_detail_storage_without_postprocessing(
    tmp_path: Path, source: str
) -> None:
    probe = Path(__file__).with_name("collection_record_isolation_probe.py")
    result = subprocess.run(
        [sys.executable, str(probe), str(tmp_path), source],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "seed/detail persisted, legacy retained, postprocessing absent" in result.stdout
    )
