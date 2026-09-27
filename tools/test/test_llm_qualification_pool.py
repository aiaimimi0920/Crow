import json
import time

import pytest
import requests

from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_cases import CASES, INSTRUCTION, exact_match
from src.llm_qualification_pool import QualifiedModelPool, eligible_model
from src.llm_qualification_store import QualificationStore


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def iter_content(self, chunk_size):
        yield json.dumps(self.body).encode()

    def close(self):
        pass


class Session:
    def __init__(self, models):
        self.models = models
        self.calls = []
        self.failed = set()

    def get(self, *_args, **_kwargs):
        return Response({"data": [{"id": name} for name in self.models]})

    def post(self, _url, *, json, **_kwargs):
        model = json["model"]
        self.calls.append(model)
        if model in self.failed:
            raise requests.Timeout("no raw provider error should enter state")
        messages = json["messages"]
        if len(messages) == 2:
            import json as json_module

            prompt = INSTRUCTION + json_module.loads(messages[1]["content"])["source_evidence"]
        else:
            prompt = messages[0]["content"]
        answer = "production"
        for index, (source, expected) in enumerate(CASES):
            if prompt == INSTRUCTION + source:
                score = self.models[model]
                answer = expected if index < score else "wrong"
        return Response({"choices": [{"message": {"content": answer}}]})

    def close(self):
        pass


def make_pool(tmp_path, models, **overrides):
    config = {"base_url": "https://models.example.test/v1", "api_key": "test-key",
              "model": "a", "models": [], "timeout": 10, **overrides}
    store = QualificationStore(config, tmp_path / "private" / "pool.sqlite3")
    # Rate scheduling is exercised separately with a deterministic clock.
    store.reserve_request_slot = lambda: 0
    session = Session(models)
    return QualifiedModelPool(config, store=store, session=session)


@pytest.mark.parametrize("model", ["gpt-5.4", "openai/gpt-oss-120b", "codex-auto-review",
    "o3", "provider/openai/o3", "provider/o1-mini", "gpt-image-2", "FLUX.2-dev",
    "mimo-v2.5-tts", "Qwen3-Embedding-8B", "Qwen3-Reranker-8B", "", None])
def test_excluded_models_never_eligible(model):
    assert not eligible_model(model)


def test_five_exact_cases_ranking_and_no_excluded_calls(tmp_path):
    pool = make_pool(tmp_path, {"a": 5, "b": 4, "c": 3, "d": 5, "e": 5, "f": 5,
                                "g": 4, "gpt-5.4": 5, "o3": 5})
    selected = pool.ensure()
    assert len(selected) == 5
    assert {"a", "d", "e", "f"}.issubset(selected)
    assert "c" not in selected
    assert len(pool.session.calls) == 35
    assert "gpt-5.4" not in pool.session.calls and "o3" not in pool.session.calls
    rows = pool.store.snapshot()["models"]
    assert rows["b"]["matches"] == [1, 1, 1, 1, 0]
    assert rows["c"]["score"] == 3
    assert pool.ensure() == selected
    assert len(pool.session.calls) == 35


def test_exact_means_no_fuzzy_or_markdown_grading():
    expected = CASES[0][1]
    assert exact_match("\n" + expected + "\n", expected)
    assert not exact_match("```json\n" + expected + "```", expected)
    assert not exact_match(expected.replace(":", ": "), expected)
    assert len(CASES) == 5
    for _source, answer in CASES:
        assert list(json.loads(answer)) == ["price_yuan", "area_sqm", "sold"]


def test_failure_cools_route_and_falls_back_without_retrying_bad_model(tmp_path):
    pool = make_pool(tmp_path, {"a": 5, "b": 5})
    pool.ensure()
    first = pool.available()[0]
    pool.session.failed.add(first)
    assert pool.chat("real item") == "production"
    assert first not in pool.available()
    assert pool.store.snapshot()["models"][first]["blocked_until"] > time.time()
    pool.session.failed.update(pool.available())
    with pytest.raises(LLMBackendUnavailableError, match="exhausted"):
        pool.chat("another item")


def test_shared_single_flight_key_change_and_crash_recovery(tmp_path):
    pool = make_pool(tmp_path, {"a": 5})
    second = make_pool(tmp_path, {"a": 5})
    assert pool.store.claim()
    assert second.ensure() == []
    assert not second.session.calls
    pool.store.change(lambda state: state.update(lease_until=time.time() - 1))
    assert second.ensure() == ["a"]
    changed = make_pool(tmp_path, {"b": 5}, api_key="changed-key")
    assert changed.available() == []
    assert changed.store.key != pool.store.key
    assert b"test-key" not in pool.store.path.read_bytes()


def test_bounded_batches_continue_to_find_best_models(tmp_path):
    pool = make_pool(tmp_path, {f"m{i:02}": 4 if i < 8 else 5 for i in range(12)})
    pool.ensure()
    assert len(pool.session.calls) == 40
    assert not pool.store.snapshot()["scan_complete"]
    pool.ensure()
    assert len(pool.session.calls) == 40
    pool.store.change(lambda state: state.update(next_scan=0))
    selected = pool.ensure()
    assert len(pool.session.calls) == 60
    assert all(f"m{i:02}" in selected for i in range(8, 12))
    assert pool.store.snapshot()["scan_complete"]


def test_empty_catalog_and_bad_response_are_not_success(tmp_path):
    pool = make_pool(tmp_path, {})
    assert pool.ensure() == []
    pool.session.post = lambda *_a, **_kw: Response({"choices": []})
    with pytest.raises(LLMBackendUnavailableError, match="invalid chat"):
        pool.request("deepseek", "test")
    with pytest.raises(LLMBackendUnavailableError, match="excluded"):
        pool.request("gpt-5.4", "test")


def test_explicit_route_cannot_silently_fallback(tmp_path):
    pool = make_pool(tmp_path, {"a": 5, "b": 5})
    pool.ensure()
    pool.session.failed.add("a")
    before = len(pool.session.calls)
    with pytest.raises(LLMBackendUnavailableError):
        pool.chat("test", model="a")
    assert pool.session.calls[before:] == ["a"]


def test_preflight_reuses_pool_without_spending_calls(tmp_path, monkeypatch):
    from src import llm_helper, llm_openai_compatible
    from src import llm_qualification_pool
    pool = make_pool(tmp_path, {"a": 5})
    pool.ensure()
    monkeypatch.setenv("FAPAI_ANALYSIS_MODEL_POOL_ENABLED", "1")
    monkeypatch.setattr(llm_openai_compatible, "_get_openai_compatible_config", lambda: pool.config)
    monkeypatch.setattr(llm_qualification_pool, "QualifiedModelPool", lambda *_a, **_kw: pool)
    result = llm_helper.preflight_openai_compatible_backend(check_chat=True)
    assert result["chat_status_code"] == 200 and result["qualified_models"] == ["a"]
    assert len(pool.session.calls) == 5
    assert llm_helper.chat_with_glm("actual data") == "production"


def test_background_refresh_does_not_block_preflight_or_repeat_in_same_process(tmp_path, monkeypatch):
    import threading
    from src import llm_qualification_pool as module
    pool = make_pool(tmp_path, {"a": 5})
    entered, release = threading.Event(), threading.Event()
    calls = []
    def probe():
        calls.append(1)
        entered.set()
        release.wait(5)
    monkeypatch.setattr(pool, "ensure", probe)
    try:
        assert pool.refresh_in_background() == []
        assert entered.wait(2)
        assert pool.refresh_in_background() == []
        assert calls == [1]
        thread = module._REFRESH_THREADS[pool.store.key]
    finally:
        release.set()
    thread.join(2)
    assert not thread.is_alive()


def test_transport_closes_and_rejects_oversized_and_redirect_responses():
    from src.llm_qualification_transport import request_json
    session = Session({})
    response = Response({"large": "x" * 100})
    closed = []
    response.close = lambda: closed.append(True)
    session.get = lambda *_a, **_kw: response
    with pytest.raises(LLMBackendUnavailableError, match="limit"):
        request_json(session, "get", "https://example.test", timeout=10, max_bytes=20)
    assert closed == [True]
    response.status_code = 302
    with pytest.raises(LLMBackendUnavailableError, match="HTTP 302"):
        request_json(session, "get", "https://example.test", timeout=10, max_bytes=200)
    assert len(closed) == 2


def test_catalog_change_tests_unseen_ids_without_retesting_the_prefix(tmp_path):
    pool = make_pool(tmp_path, {f"m{i:02}": 0 for i in range(12)})
    pool.ensure()
    pool.session.models["aa"] = 5
    pool.store.change(lambda state: state.update(next_scan=0))
    assert "aa" in pool.ensure()
    assert pool.session.calls.count("m00") == 5
    assert len(pool.session.calls) == 65


def test_recent_failures_are_not_retested_every_empty_pool_poll(tmp_path):
    pool = make_pool(tmp_path, {"a": 0, "b": 0})
    assert pool.ensure() == []
    pool.store.change(lambda state: state.update(next_scan=0))
    assert pool.ensure() == []
    assert len(pool.session.calls) == 10
