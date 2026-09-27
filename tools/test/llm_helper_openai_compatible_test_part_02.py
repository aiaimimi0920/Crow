from __future__ import annotations

import json
import time
from typing import Any

import pytest
import requests

from src import llm_auction_extraction, llm_avm_risk, llm_helper
from tools.test.llm_helper_openai_compatible_test_context import _FakeResponse


def test_chat_with_glm_falls_back_across_openai_model_candidates(monkeypatch):
    calls: list[str] = []

    class UnavailableResponse:
        status_code = 503
        content = b'{"error":{"code":"model_not_found"}}'
        text = content.decode("utf-8")

        def raise_for_status(self) -> None:
            raise requests.HTTPError("503 Server Error", response=self)

    class SuccessfulResponse(_FakeResponse):
        content = _FakeResponse.text.encode("utf-8")

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json["model"])
            return UnavailableResponse() if json["model"] == "primary-model" else SuccessfulResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "primary-model;fallback-model")
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == '{"ok":true}'
    assert calls == ["primary-model", "fallback-model"]


def test_chat_with_glm_does_not_hide_openai_candidate_auth_failure(monkeypatch):
    calls: list[str] = []

    class UnauthorizedResponse:
        status_code = 401
        content = b'{"error":"unauthorized"}'
        text = content.decode("utf-8")

        def raise_for_status(self) -> None:
            raise requests.HTTPError("401 Client Error", response=self)

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json["model"])
            return UnauthorizedResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "bad-key")
    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "fallback-model")
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    with pytest.raises(requests.HTTPError):
        llm_helper.chat_with_glm("return json")

    assert calls == ["primary-model"]


def test_preflight_openai_compatible_backend_falls_back_across_model_candidates(monkeypatch):
    calls: list[str] = []

    class ModelsResponse:
        status_code = 200

    class ChatResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, *_args, **_kwargs):
            return ModelsResponse()

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json["model"])
            return ChatResponse(503 if json["model"] == "primary-model" else 200)

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "fallback-model")
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5, check_chat=True)

    assert result["status_code"] == 200
    assert result["chat_status_code"] == 200
    assert result["chat_model_name"] == "fallback-model"
    assert calls == ["primary-model", "fallback-model"]


def test_preflight_openai_compatible_backend_reports_network_unavailable_without_raising(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, *_args, **_kwargs):
            raise requests.ConnectTimeout("provider unavailable")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = llm_helper.preflight_openai_compatible_backend(timeout=1.0, check_chat=True)

    assert result["enabled"] is True
    assert result["status_code"] == 0
    assert result["error_type"] == "ConnectTimeout"


def test_chat_with_glm_does_not_retry_non_transient_openai_compatible_400(monkeypatch):
    calls: list[int] = []

    class BadRequestResponse:
        status_code = 400
        content = b'{"error":"bad request"}'
        text = '{"error":"bad request"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("400 Client Error", response=self)

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            calls.append(1)
            return BadRequestResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "3")
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    with pytest.raises(requests.HTTPError):
        llm_helper.chat_with_glm("return json")

    assert len(calls) == 1


def test_avm_risk_prompt_asks_for_stable_reusable_location_index_name():
    prompt = llm_helper.build_avm_risk_prompt("北京市朝阳区八里庄远洋天地小区7号楼1单元101室")

    assert "稳定位置索引名" in prompt
    assert "后续可复用" in prompt
    assert "不要求官方名称" in prompt
    assert "楼号、单元号、房号" in prompt


def test_extract_auction_data_prompt_asks_for_stable_reusable_location_index_name(monkeypatch):
    captured: dict[str, str] = {}

    def fake_chat_with_glm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "{}"

    monkeypatch.setattr(llm_auction_extraction, "chat_with_glm", fake_chat_with_glm)

    llm_helper.extract_auction_data(
        """
        <html>
          <head><title>北京市朝阳区八里庄远洋天地小区7号楼101室</title></head>
          <body><div class="item-address">北京市朝阳区八里庄远洋天地小区7号楼101室</div></body>
        </html>
        """,
        item_id="prompt-contract",
    )

    prompt = captured["prompt"]
    assert "稳定位置索引名" in prompt
    assert "后续归并、索引同片房源" in prompt
    assert "不要求它是官方名称" in prompt
    assert "不要输出城市、区县、道路门牌号、楼号、单元号、房号" in prompt


def test_extract_avm_risk_features_normalizes_list_evidence_source(monkeypatch):
    payload = {key: None for key in llm_helper.AVM_RISK_KEYS}
    payload.update(
        {
            "community_name": "朝阳门内大街288号院",
            "land_right_type": "未知",
            "floor_level": "中区",
            "orientation": "未知",
            "tax_burden": "未知",
            "housing_type": "住宅",
            "extraction_confidence": 0.8,
            "evidence_span": ["页面标题"],
            "evidence_source": ["页面主文", "公告"],
            "extraction_version": "avm_risk_v2",
        }
    )

    monkeypatch.setattr(llm_avm_risk, "chat_with_glm", lambda _prompt: json.dumps(payload, ensure_ascii=False))

    features = llm_helper.extract_avm_risk_features("北京市东城区朝阳门内大街288号院3号楼", item_id="risk-list-source")

    assert features is not None
    assert features["evidence_source"] == "页面主文"


def test_extract_area_from_text_prefers_building_area_over_land_area():
    text = "标的物宗地面积为300.00㎡，房屋建筑面积为120.50㎡，用途为住宅。"

    assert llm_helper.extract_area_from_text(text) == 120.5


def test_fetch_description_data_text_decodes_gbk_description(monkeypatch):
    desc_html = "拍卖对象为北京市东城区测试房产，面积为88.88㎡。"
    html = """
    <html>
      <body>
        <script id="description-data" type="text/json">
          {&quot;link&quot;:&quot;https://itemcdn.tmall.com/desc/icoss!gbk!1&quot;}
        </script>
      </body>
    </html>
    """

    class FakeResponse:
        content = desc_html.encode("gb18030")
        text = ""

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            assert self.trust_env is False
            return FakeResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    text = llm_helper.fetch_description_data_text(html)

    assert "面积为88.88㎡" in text
    assert llm_helper.extract_area_from_text(text) == 88.88


def test_extract_auction_data_backfills_area_from_description_data_link(monkeypatch):
    desc_html = (
        "<table><tr><td>拍品介绍</td><td>"
        "拍卖对象为北京市东城区朝阳门内大街288号院3号楼1单元1502号房产，面积为117.06㎡。"
        "</td></tr></table>"
    )
    html = """
    <html>
      <head><title>北京市东城区朝阳门内大街288号院3号楼1单元1502号房产</title></head>
      <body>
        <script id="description-data" type="text/json">
          {&quot;link&quot;:&quot;https://itemcdn.tmall.com/desc/icoss!0747988656830!11064941259?var=desc?var=desc&quot;}
        </script>
        <div id="J_desc">标的物详情加载中......</div>
      </body>
    </html>
    """

    captured: dict[str, str] = {}

    def fake_chat_with_glm(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {
                "id": 747988656830,
                "市场评估价": 9001680,
                "起拍价格": 13554680,
                "成交价格": 13554680,
                "标题": "北京市东城区朝阳门内大街288号院3号楼1单元1502号房产",
                "是否成交": True,
                "完整地址": "北京市东城区朝阳门内大街288号院3号楼1单元1502号房产",
                "所属小区": "朝阳门内大街288号院",
                "城市": "北京市",
                "区": "东城区",
                "建筑面积": None,
                "单价": 0,
                "is_processed": True,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_auction_extraction, "chat_with_glm", fake_chat_with_glm)

    class FakeResponse:
        content = desc_html.encode("utf-8")
        text = desc_html

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.urls: list[str] = []

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            self.urls.append(url)
            assert self.trust_env is False
            assert "itemcdn.tmall.com/desc/" in url
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(requests, "Session", lambda: fake_session)

    result = json.loads(llm_helper.extract_auction_data(html, item_id="747988656830"))

    assert result["建筑面积"] == 117.06
    assert result["产权建筑面积"] == 117.06
    assert result["单价"] == round(13554680 / 117.06, 2)
    assert "异步标的物描述" in captured["prompt"]
    assert "面积为117.06㎡" in captured["prompt"]


def test_extract_auction_data_uses_description_area_as_gross_area_for_fractional_share(monkeypatch):
    desc_html = "拍卖标的为某房产二分之一产权，房屋建筑面积为120.00㎡。"
    html = """
    <html>
      <head><title>北京市朝阳区测试小区1号楼101室二分之一产权</title></head>
      <body>
        <script id="description-data" type="text/json">
          {&quot;link&quot;:&quot;https://itemcdn.tmall.com/desc/icoss!fractional!1&quot;}
        </script>
      </body>
    </html>
    """

    monkeypatch.setattr(
        llm_auction_extraction,
        "chat_with_glm",
        lambda _prompt: json.dumps(
            {
                "id": 1,
                "成交价格": 6000000,
                "完整地址": "北京市朝阳区测试小区1号楼101室",
                "所属小区": "测试小区",
                "建筑面积": None,
                "产权建筑面积": None,
                "产权份额比例": 0.5,
                "单价": 0,
                "is_processed": True,
            },
            ensure_ascii=False,
        ),
    )

    class FakeResponse:
        content = desc_html.encode("utf-8")
        text = desc_html

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            assert self.trust_env is False
            return FakeResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = json.loads(llm_helper.extract_auction_data(html, item_id="fractional"))

    assert result["产权建筑面积"] == 120.0
    assert result["建筑面积"] == 60.0
    assert result["单价"] == 100000.0
