"""Exercise the production composition in fresh processes with real storage."""

from pathlib import Path

import pytest

from tools.test.collection_probe_runner import SOURCES, run_source_probes


@pytest.fixture(scope="module")
def application_results(tmp_path_factory):
    probe = Path(__file__).with_name("collection_application_probe.py")
    return run_source_probes(
        probe,
        tmp_path_factory.mktemp("collection-applications"),
        timeout=35,
    )


@pytest.mark.parametrize("source", SOURCES)
def test_collection_api_start_accept_and_stop_without_postprocessing(
    application_results, source
):
    result = application_results[source]
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert (
        "collection API: seed, HTML, storage, workers stopped; postprocessing absent"
        in result.stdout
    )
