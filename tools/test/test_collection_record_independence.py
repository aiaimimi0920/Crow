from __future__ import annotations

from pathlib import Path

import pytest

from tools.test.collection_probe_runner import SOURCES, run_source_probes


@pytest.fixture(scope="module")
def storage_results(tmp_path_factory):
    probe = Path(__file__).with_name("collection_record_isolation_probe.py")
    return run_source_probes(
        probe,
        tmp_path_factory.mktemp("collection-repositories"),
        timeout=30,
    )


@pytest.mark.parametrize("source", SOURCES)
def test_seed_detail_storage_without_postprocessing(storage_results, source: str):
    result = storage_results[source]
    assert result.returncode == 0, result.stdout + result.stderr
    assert "collection status HTTP passed without postprocessing" in result.stdout
    assert (
        "seed/detail persisted, legacy retained, postprocessing absent" in result.stdout
    )
