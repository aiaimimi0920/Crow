"""Manual review status preserves repository selection and audit boundaries."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import manual_review_status


def test_native_status_import_does_not_initialize_server():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from src.avm import operator_evaluation; "
                "from src import manual_review_context, manual_review_status, manual_review_validation; "
                "assert 'src.server_context' not in sys.modules; "
                "assert 'src.server' not in sys.modules; "
                "from tools.backfill_manual_review_control_plane_to_db import _build_repo; "
                "provided = object(); assert _build_repo(None, provided) is provided; "
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


def test_repository_type_error_is_not_retried_against_json(tmp_path, monkeypatch):
    from src import server

    repository = SimpleNamespace(enabled=True)
    calls = []

    def load(path, *, repository=None):
        calls.append((path, repository))
        if repository is not None:
            raise TypeError("invalid persisted receipt")
        return {"receipts": []}

    monkeypatch.setattr(server, "DB_REPOSITORY", repository)
    monkeypatch.setattr(
        manual_review_status, "load_manual_review_receipt_snapshot", load
    )
    with pytest.raises(TypeError, match="invalid persisted receipt"):
        server._load_manual_review_receipt_snapshot_for_runtime(tmp_path)
    assert calls == [(tmp_path / "avm" / "manual_review_receipts.json", repository)]


@pytest.mark.parametrize("entrypoint", ["native", "facade"])
@pytest.mark.parametrize("enabled", [False, True])
def test_receipt_reader_uses_current_repository(
    tmp_path, monkeypatch, entrypoint, enabled
):
    from src import server

    calls = []
    snapshot = {"receipts": [{"action": "manual_location_review"}]}

    def load(path, *, repository):
        calls.append((path, repository))
        return snapshot

    monkeypatch.setattr(
        manual_review_status, "load_manual_review_receipt_snapshot", load
    )
    for _ in range(2):
        repository = SimpleNamespace(enabled=enabled)
        if entrypoint == "native":
            result = (
                manual_review_status._load_manual_review_receipt_snapshot_for_runtime(
                    tmp_path, repository=repository
                )
            )
        else:
            monkeypatch.setattr(server, "DB_REPOSITORY", repository)
            result = server._load_manual_review_receipt_snapshot_for_runtime(tmp_path)
        assert result is snapshot
        assert calls[-1] == (
            tmp_path / "avm" / "manual_review_receipts.json",
            repository if enabled else None,
        )
    assert len(calls) == 2


@pytest.mark.parametrize("entrypoint", ["native", "facade"])
def test_runtime_summary_records_once_before_reading_history(
    tmp_path, monkeypatch, entrypoint
):
    from src import server

    repository = SimpleNamespace(enabled=False)
    original_record = manual_review_status.record_manual_review_control_plane_integrity
    original_history = (
        manual_review_status.load_manual_review_control_plane_integrity_history
    )
    events = []

    def record(data_root, integrity):
        events.append("record")
        return original_record(data_root, integrity)

    def history(data_root):
        events.append("history")
        return original_history(data_root)

    monkeypatch.setattr(
        manual_review_status, "record_manual_review_control_plane_integrity", record
    )
    monkeypatch.setattr(
        manual_review_status,
        "load_manual_review_control_plane_integrity_history",
        history,
    )
    if entrypoint == "native":
        result = manual_review_status._manual_review_control_plane_runtime_summary(
            tmp_path, repository=repository
        )
    else:
        monkeypatch.setattr(server, "DB_REPOSITORY", repository)
        result = server._manual_review_control_plane_runtime_summary(tmp_path)
    assert events == ["record", "history"]
    assert (
        result["manual_review_control_plane_integrity"]["integrity_status"]
        == "healthy_json_runtime"
    )
    assert (
        result["manual_review_control_plane_integrity_history_summary"][
            "last_integrity_status"
        ]
        == "healthy_json_runtime"
    )
    assert (
        result["manual_review_control_plane_guidance"]["guidance_status"]
        == "no_action_required"
    )
