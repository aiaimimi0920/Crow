"""Legacy snapshot formatting preserves values without regex backtracking."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from jobs.job_json import format_job_json
from jobs.job_manager import JobManager

pytestmark = [pytest.mark.security, pytest.mark.unit]


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        [0, 1, 100],
        {"pages": [0, 1, 12], "done": False},
        {"pages": [-1, 0, 1.5, True, None, "一"]},
        {"nested": [[1, 2], [3, 4]], "strings": ["[\n1\n]", "[", "]"]},
        {"mixed": [1, 2, "stop", [3, 4], {"pages": [5, 6]}]},
        {"pages": [12345678901234567890], "meta": {"page": [5]}},
    ],
)
def test_formatter_roundtrips_every_json_value(value):
    assert json.loads(format_job_json(value)) == value


def test_nonnegative_page_arrays_keep_legacy_compact_layout():
    assert format_job_json({"pages": [0, 1, 12], "done": False}) == (
        '{\n  "pages": [0, 1, 12],\n  "done": false\n}'
    )
    assert format_job_json([1, 2, 3]) == "[1, 2, 3]"


def test_mixed_array_and_embedded_array_text_remain_pretty_printed():
    data = {"pages": [1, 2, "not a page"], "text": "[\n  1,\n  2\n]"}
    assert format_job_json(data) == json.dumps(data, ensure_ascii=False, indent=2)


def test_large_numeric_prefix_then_non_numeric_value_finishes_in_bounded_process():
    # The old nested quantified regex backtracked over a valid JSON mixed array.
    source = (
        "import json; from jobs.job_json import format_job_json; "
        "data={'pages':list(range(10000))+['stop'],'nested':[[1,2],[3,4]]}; "
        "assert json.loads(format_job_json(data)) == data"
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_atomic_snapshot_save_preserves_mixed_data_and_cache(tmp_path):
    manager = JobManager(str(tmp_path))
    path = tmp_path / "4401.json"
    data = {"pages": list(range(100)) + ["stop"], "nested": {"pages": [1, 2]}}
    manager._save_job_file(str(path), data)
    assert json.loads(path.read_text(encoding="utf-8")) == data
    assert manager._load_job_file(str(path)) == data
    assert not list(tmp_path.glob("*.tmp"))


def test_direct_legacy_script_still_imports_formatter_without_repository_path(tmp_path):
    root = Path(__file__).resolve().parents[2]
    for name in ("job_manager.py", "job_json.py"):
        shutil.copyfile(root / "jobs" / name, tmp_path / name)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, str(tmp_path / "job_manager.py")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert "Usage: python job_manager.py" in result.stdout
    assert "ImportError" not in result.stderr
