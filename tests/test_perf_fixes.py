"""Performance fixes retain structured evidence and final-answer semantics."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from src import llm_openai_compatible as rest
from src import llm_text_extraction as extraction
from src.html_parse import parse_html


class Response:
    def __init__(self, message):
        self.message = message

    def json(self):
        return {"choices": [{"message": self.message, "finish_reason": "stop"}]}


def test_filter_retains_table_relationships_and_caches(monkeypatch):
    html = '<table class="evidence"><tr><th>建筑面积</th><td>100㎡</td></tr></table><script>secret</script>'
    extraction._FILTER_CACHE.clear()
    first = extraction.filter_content(html)
    assert "secret" not in first and "class=" not in first
    assert "<th>建筑面积</th><td>100㎡</td>" in first
    monkeypatch.setattr(
        extraction, "_filter_content_uncached", lambda _: pytest.fail("cache missed")
    )
    assert extraction.filter_content(html) == first


@pytest.mark.parametrize("value", [None, "", "   ", {"text": "not content"}, 42])
def test_reasoning_is_never_promoted_to_final_answer(value):
    assert (
        rest._message_text(
            Response({"content": value, "reasoning_content": "猜测价格100万"})
        )[0]
        is None
    )


def test_structured_final_text():
    assert (
        rest._message_text(
            Response({"content": [{"type": "text", "text": "最终答案"}]})
        )[0]
        == "最终答案"
    )


def test_http_pool_is_thread_and_credential_isolated():
    first = rest._get_http_session("https://api.example.invalid", {}, "one")
    assert rest._get_http_session("https://api.example.invalid", {}, "one") is first
    with ThreadPoolExecutor(max_workers=1) as pool:
        other = pool.submit(
            rest._get_http_session, "https://api.example.invalid", {}, "one"
        ).result()
    assert other is not first
    second = rest._get_http_session("https://api.example.invalid", {}, "two")
    assert second is not first
    assert second.trust_env is False
    second.close()
    other.close()


def test_fast_parser_propagates_unexpected_errors(monkeypatch):
    from src import html_parse

    def broken(*args):
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(html_parse, "BeautifulSoup", broken)
    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        parse_html("<p>test</p>")


def test_empty_model_does_not_suppress_other_models_transient_retry(monkeypatch):
    calls = []

    class FakeResponse(Response):
        def __init__(self, status_code, message):
            super().__init__(message)
            self.status_code = status_code
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("unexpected exhausted backend")

    class FakeSession(rest.requests.sessions.Session):
        def post(self, url, **kwargs):
            model = kwargs["json"]["model"]
            calls.append(model)
            if model == "empty":
                return FakeResponse(
                    200, {"content": "", "reasoning_content": "not final"}
                )
            if calls.count("recovering") == 1:
                return FakeResponse(503, {})
            return FakeResponse(200, {"content": '{"ok":true}'})

    monkeypatch.setattr(rest.requests, "Session", FakeSession)
    monkeypatch.setattr(rest.time, "sleep", lambda _: None)
    config = {
        "base_url": "https://api.example.invalid",
        "api_key": "test",
        "timeout": 1,
        "max_retries": 2,
        "model": "recovering",
        "models": ["recovering", "empty"],
    }
    assert rest._chat_with_openai_compatible("evidence", config) == '{"ok":true}'
    assert calls == ["recovering", "empty", "recovering"]
    assert config["last_successful_model"] == "recovering"
