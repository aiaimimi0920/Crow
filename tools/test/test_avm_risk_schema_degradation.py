"""AVM 风险抽取的字段级降级校验。

历史行为是整条否决：任意字段不合规就 `return None`，整条抽取结果被丢弃。
线上后果是 228,959 条记录风险字段全空——`orientation` 返回"东南"这类
枚举外的合法真实值，会把同一条里已经正确抽出的 is_occupied / clear_delivery /
build_year 一起带走。这里固化的预期是：坏字段降级为 None，好字段必须留下。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _base_features() -> dict:
    from src.llm_helper import AVM_RISK_KEYS

    features = {key: None for key in AVM_RISK_KEYS}
    features["extraction_confidence"] = 0.8
    features["evidence_source"] = "公告"
    features["evidence_span"] = ""
    return features


def test_out_of_enum_orientation_is_dropped_but_other_fields_survive() -> None:
    from src.llm_helper import sanitize_avm_risk_features

    # “东南”是真实且常见的朝向，但不在枚举内；它不该带走整条记录
    features = dict(
        _base_features(),
        orientation="东南",
        is_occupied=True,
        clear_delivery=False,
        has_long_lease=False,
        build_year=2010,
        housing_type="住宅",
        land_right_type="出让",
        tax_burden="买受人承担全部",
    )

    sanitized, dropped = sanitize_avm_risk_features(features, item_id="T1")

    assert sanitized is not None
    assert sanitized["orientation"] is None
    assert "orientation" in dropped
    # 同一条里正确的字段必须全部保留
    assert sanitized["is_occupied"] is True
    assert sanitized["clear_delivery"] is False
    assert sanitized["has_long_lease"] is False
    assert sanitized["build_year"] == 2010
    assert sanitized["housing_type"] == "住宅"
    assert sanitized["land_right_type"] == "出让"
    assert sanitized["tax_burden"] == "买受人承担全部"


def test_wrong_typed_boolean_is_dropped_without_losing_siblings() -> None:
    from src.llm_helper import sanitize_avm_risk_features

    features = dict(
        _base_features(),
        is_occupied="是",  # 应为 bool
        clear_delivery=True,
        is_haunted=False,
    )

    sanitized, dropped = sanitize_avm_risk_features(features, item_id="T2")

    assert sanitized is not None
    assert sanitized["is_occupied"] is None
    assert "is_occupied" in dropped
    assert sanitized["clear_delivery"] is True
    assert sanitized["is_haunted"] is False


def test_out_of_range_confidence_falls_back_instead_of_dropping_record() -> None:
    from src.llm_helper import sanitize_avm_risk_features

    features = dict(_base_features(), extraction_confidence=7.5, is_occupied=True)

    sanitized, dropped = sanitize_avm_risk_features(features, item_id="T3")

    assert sanitized is not None
    assert sanitized["extraction_confidence"] is None
    assert "extraction_confidence" in dropped
    assert sanitized["is_occupied"] is True


def test_non_numeric_build_year_is_dropped_but_record_survives() -> None:
    from src.llm_helper import sanitize_avm_risk_features

    features = dict(_base_features(), build_year="约2010年", total_floors=18)

    sanitized, dropped = sanitize_avm_risk_features(features, item_id="T4")

    assert sanitized is not None
    assert sanitized["build_year"] is None
    assert "build_year" in dropped
    assert sanitized["total_floors"] == 18


def test_fully_valid_payload_reports_no_dropped_fields() -> None:
    from src.llm_helper import sanitize_avm_risk_features

    features = dict(
        _base_features(),
        orientation="南北",
        is_occupied=False,
        housing_type="住宅",
        build_year=2015,
    )

    sanitized, dropped = sanitize_avm_risk_features(features, item_id="T5")

    assert dropped == []
    assert sanitized["orientation"] == "南北"
    assert sanitized["is_occupied"] is False
    assert sanitized["build_year"] == 2015


def test_non_dict_payload_is_still_rejected_outright() -> None:
    from src.llm_helper import sanitize_avm_risk_features

    # 结构性错误（不是 dict）无法字段级降级，仍应整体拒绝
    sanitized, dropped = sanitize_avm_risk_features(["not", "a", "dict"], item_id="T6")

    assert sanitized is None
    assert dropped == []


def test_extract_avm_risk_features_keeps_partial_payload(monkeypatch) -> None:
    """端到端：LLM 返回枚举外朝向时，抽取不再整条返回 None。"""
    import json

    from src import llm_avm_risk, llm_helper

    payload = dict(
        _base_features(),
        orientation="西南",
        is_occupied=True,
        clear_delivery=False,
        housing_type="住宅",
    )
    monkeypatch.setattr(llm_avm_risk, "chat_with_glm", lambda prompt: json.dumps(payload, ensure_ascii=False))

    result = llm_helper.extract_avm_risk_features("公告正文", item_id="E2E")

    assert result is not None, "枚举外朝向不应导致整条抽取被丢弃"
    assert result["orientation"] is None
    assert result["is_occupied"] is True
    assert result["clear_delivery"] is False
    assert result["housing_type"] == "住宅"


def test_validate_helper_still_reports_errors_for_observability() -> None:
    """校验函数本身保留，用于日志与门禁观测。"""
    from src.llm_helper import validate_avm_risk_features_schema

    features = dict(_base_features(), orientation="东南")
    passed, errors = validate_avm_risk_features_schema(features, item_id="OBS")

    assert passed is False
    assert any("orientation" in e for e in errors)
