"""Cooperative stops cross real maintenance boundaries without undoing evidence."""

import json
from types import SimpleNamespace

import pytest

from src import collection_job_control
from src.collection_job_control import JobControl, JobStopped, job_scope


@pytest.mark.parametrize("deadline_first", [True, False])
def test_early_event_wait_return_cannot_advance_a_job_phase(
    monkeypatch, deadline_first
):
    now = [0.0]
    monkeypatch.setattr(
        collection_job_control, "time", SimpleNamespace(monotonic=lambda: now[0])
    )
    control = JobControl(1 if deadline_first else 5)
    wake_times = iter([0.5, 1.0])

    def early_wait(_seconds):
        # Event waits and the monotonic clock can have different timer resolution.
        now[0] = next(wake_times)
        return False

    monkeypatch.setattr(control._event, "wait", early_wait)
    if deadline_first:
        with pytest.raises(JobStopped) as stopped:
            control.wait(5)
        assert stopped.value.reason == "timed_out"
    else:
        control.wait(1)
        assert control.stop_reason() is None
    assert now[0] == 1.0


def test_replay_cancellation_before_publish_keeps_archive_bytes(tmp_path, monkeypatch):
    from tools import prepare_recent_detail_replay as replay

    control = JobControl(10)
    archive = tmp_path / "archive.json"
    original = json.dumps(
        [{"id": "item", "detail_captured": True, "url": "https://example.test/item"}]
    ).encode()
    archive.write_bytes(original)
    monkeypatch.setattr(
        replay,
        "_iter_recent_rows",
        lambda *_args, **_kwargs: [{"__file_path": str(archive)}],
    )
    monkeypatch.setattr(
        replay, "create_repository_from_env", lambda: SimpleNamespace(enabled=False)
    )

    def resolve(row):
        control.request_stop("cancelled")
        return row["url"]

    monkeypatch.setattr(replay, "_resolve_detail_url", resolve)
    with pytest.raises(JobStopped), job_scope(control):
        replay.prepare_recent_detail_replay(tmp_path, window_days=7, limit=1)
    assert archive.read_bytes() == original


def test_fetch_uses_remaining_budget_and_stops_before_artifact_writes(
    tmp_path, monkeypatch
):
    from src.collection import detail_archive_fetch as fetch

    archive = tmp_path / "archive.json"
    original = b'[{"id":"item"}]'
    archive.write_bytes(original)
    control = JobControl(10)
    timeouts = []

    class Session:
        headers = {}

        def get(self, _url, *, timeout):
            timeouts.append(timeout)
            control.request_stop("cancelled")
            return SimpleNamespace(raise_for_status=lambda: None, text="safe " * 100)

    monkeypatch.setattr(fetch.requests, "Session", Session)
    monkeypatch.setattr(
        fetch,
        "create_repository_from_env",
        lambda: SimpleNamespace(
            enabled=True,
            iter_detail_fetch_candidates=lambda **_: [
                {
                    "id": "item",
                    "__file_path": str(archive),
                    "url": "https://example.test/item",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        fetch,
        "extract_detail_artifacts",
        lambda **_: pytest.fail("cancelled fetch wrote artifacts"),
    )
    with pytest.raises(JobStopped), job_scope(control):
        fetch.fetch_missing_detail_archives(tmp_path, limit=1, timeout=30)
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 10
    assert archive.read_bytes() == original
    assert list(tmp_path.iterdir()) == [archive]


def test_pipeline_stop_finishes_current_stage_and_skips_following_stages(
    tmp_path, monkeypatch
):
    from src.avm.pipeline import AVMPipelineConfig, AVMPipelineManager
    from tools import build_avm_features, build_canonical_dataset

    control = JobControl(10)
    pipeline = AVMPipelineManager(str(tmp_path))

    def build(**_options):
        control.request_stop("cancelled")
        return {"confirmed": True}

    monkeypatch.setattr(build_canonical_dataset, "build_canonical_dataset", build)
    monkeypatch.setattr(
        build_avm_features,
        "build_avm_features",
        lambda **_: pytest.fail("next stage ran"),
    )
    with pytest.raises(JobStopped), job_scope(control):
        pipeline.run(config=AVMPipelineConfig(data_dir=str(tmp_path)))
    state = pipeline.status()
    assert state["running"] is False and state["finished_at"]
    assert state["current_task"] is None
    assert len(state["tasks"]) == 1
    assert state["tasks"][0]["status"] == "cancelled"
    assert state["tasks"][0]["finished_at"]
