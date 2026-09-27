"""Operator previews preserve source artifacts through native and facade calls."""

import pytest

from src import server_hybrid_context


@pytest.fixture(params=["native", "facade"])
def preview(request):
    if request.param == "native":
        return server_hybrid_context._avm_operator_eval_summary
    from src import server

    return server._avm_operator_eval_summary


def test_missing_evaluation_is_read_only_and_has_no_ready_patch(tmp_path, preview):
    result = preview(tmp_path)
    assert result["calibration_target_counts"] == {
        "global_risk": 0,
        "risk_factor": 0,
        "temporal": 0,
        "strategy": 0,
    }
    assert result["calibration_patch_preview"]["patch_ready"] is False
    assert result["recommended_bundle_patch_preview"]["patch_ready"] is False
    assert not (tmp_path / "avm").exists()


def test_invalid_preview_artifacts_are_preserved(tmp_path, preview):
    root = tmp_path / "avm"
    root.mkdir()
    inputs = {
        "config.json": b'{"unfinished":',
        "calibration_targets.json": b'["invalid shape"]',
        "release_gate.json": b"null",
    }
    for name, raw in inputs.items():
        (root / name).write_bytes(raw)
    result = preview(tmp_path)
    assert result["calibration_patch_preview"]["patch_ready"] is False
    assert {p.name: p.read_bytes() for p in root.iterdir()} == inputs
