"""Continuous workers retain only the history actually exposed in their summary."""

import gc
import importlib
import weakref
from types import SimpleNamespace

import pytest

from tools import worker_lifecycle


@pytest.mark.parametrize(
    "module_name", ["tools.detail_worker", "tools.detail_worker_loop"]
)
@pytest.mark.parametrize("bounded", [False, True])
def test_batch_history_is_bounded_while_worker_is_running(
    monkeypatch, tmp_path, module_name, bounded
):
    module = importlib.import_module(module_name)
    references = []
    summaries = []
    total = 32

    class Batch(dict):
        pass

    def batch(*_args, **_kwargs):
        if len(references) >= 21:
            gc.collect()
            assert sum(reference() is not None for reference in references) <= 20
        value = Batch(
            decision="detail_worker_batch_finished", number=len(references) + 1
        )
        references.append(weakref.ref(value))
        return value

    monkeypatch.setattr(module, "run_detail_worker_batch", batch)
    monkeypatch.setattr(
        module, "_detail_batch_progress_event", lambda *_args: {}, raising=False
    )
    monkeypatch.setattr(
        module,
        "_write_runtime_summary",
        lambda _path, value: summaries.append(value),
        raising=False,
    )
    monkeypatch.setattr(module, "_detail_batch_sleep_seconds", lambda *_args: 0)
    monkeypatch.setattr(
        worker_lifecycle, "checkpoint", lambda _stage: len(references) < total
    )
    config = module.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="",
        target_success=1,
        max_attempts=1,
        worker_id="history-test",
        do_risk=False,
        max_runs=total if bounded else None,
    )
    result = module.run_detail_worker_loop(
        config,
        repository=SimpleNamespace(seed_queue_counts=dict),
        http_session=object(),
        browser_pages={},
        progress_emit_func=lambda _value: None,
    )
    assert result["runs"] == total
    assert result["last_decision"] == "detail_worker_batch_finished"
    assert [row["number"] for row in result["results"]] == list(range(13, 33))
    assert summaries == [result]
    gc.collect()
    assert sum(reference() is not None for reference in references) == 20
