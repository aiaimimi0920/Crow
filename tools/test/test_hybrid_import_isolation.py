"""Read-only hybrid and stage summaries do not initialize server globals."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.utc_timestamps",
        "src.server_hybrid_escalation",
        "src.server_hybrid_operator_summary",
        "src.server_hybrid_policy",
        "src.hybrid_collection_status",
        "src.collection_stage_status",
    ],
)
def test_native_summary_import_does_not_initialize_server(module_name):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, sys; "
                f"importlib.import_module({module_name!r}); "
                "assert 'src.server_context' not in sys.modules; "
                "assert 'src.server' not in sys.modules; "
                "assert 'src.storage' not in sys.modules; "
                "assert 'sqlalchemy' not in sys.modules"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
