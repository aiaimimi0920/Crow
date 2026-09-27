from __future__ import annotations

from pathlib import Path

from tools import operator_entrypoints


def test_parse_batch_python_target_extracts_wrapped_python_script():
    text = """
@echo off
cd /d "%~dp0.."
"%PYTHON_CMD%" src/server.py
pause
"""

    assert operator_entrypoints.parse_batch_python_target(text) == Path("src/server.py")


def test_repo_operator_entrypoints_inventory_matches_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert operator_entrypoints.repo_operator_entrypoints(repo_root) == [
        repo_root / "auto" / "data_fixer.bat",
        repo_root / "auto" / "main.bat",
        repo_root / "auto" / "seed_hybrid_collector.bat",
    ]


def test_repo_operator_entrypoints_point_to_existing_python_targets():
    repo_root = Path(__file__).resolve().parents[2]

    records = operator_entrypoints.collect_batch_python_entrypoints(repo_root)

    assert [
        (record.script_path.relative_to(repo_root), record.target_path)
        for record in records
    ] == [
        (Path("auto/data_fixer.bat"), Path("src/data_fixer.py")),
        (Path("auto/main.bat"), Path("tools/run_collection_api.py")),
        (
            Path("auto/seed_hybrid_collector.bat"),
            Path("tools/run_hybrid_seed_collection.py"),
        ),
    ]
    assert all(record.uses_repo_root_pushd for record in records)
    assert all((repo_root / record.target_path).exists() for record in records)
