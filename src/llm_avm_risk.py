from __future__ import annotations

import json
import logging

from src.llm_auction_extraction import build_avm_risk_prompt
from src.llm_openai_compatible import chat_with_glm


logger = logging.getLogger(__name__)


AVM_RISK_BOOLEAN_FIELDS = {
    "has_elevator",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "is_haunted",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
}


AVM_RISK_NUMERIC_FIELDS = {
    "build_year",
    "total_floors",
    "evaluation_price",
}


AVM_RISK_ENUM_FIELDS = {
    "floor_level": {"低区", "中区", "高区", "顶层", "底层", "独栋"},
    "orientation": {"南", "南北", "东", "西", "北", "未知"},
    "land_right_type": {"出让", "划拨", "未知"},
    "tax_burden": {"买受人承担全部", "各自承担", "未知"},
    "housing_type": {"住宅", "别墅", "商业", "办公", "工业", "车位", "其他"},
}


AVM_RISK_KEYS = [
    "community_name",
    "build_year",
    "total_floors",
    "floor_level",
    "has_elevator",
    "orientation",
    "land_right_type",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "is_haunted",
    "housing_type",
    "has_keys",
    "property_fee_owed",
    "special_school_tag",
    "evaluation_price",
    "layout",
    "is_restricted_purchase",
    "includes_parking",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
]


AVM_RISK_AUDIT_KEYS = [
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
]


def validate_avm_risk_features_schema(features, item_id=None):
    """
    Hand-written schema validation for AVM risk extraction.
    Returns (passed, errors).
    """
    errors = []
    item_label = item_id if item_id is not None else "unknown"

    if not isinstance(features, dict):
        return False, [f"item={item_label}: payload is not a dict"]

    for key in AVM_RISK_KEYS:
        if key not in features:
            errors.append(f"item={item_label}: missing key '{key}'")

    for key in AVM_RISK_BOOLEAN_FIELDS:
        value = features.get(key)
        if value is not None and not isinstance(value, bool):
            errors.append(f"item={item_label}: '{key}' expects bool/null, got {type(value).__name__}")

    for key in AVM_RISK_NUMERIC_FIELDS:
        value = features.get(key)
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"item={item_label}: '{key}' expects number/null, got {type(value).__name__}")

    extraction_confidence = features.get("extraction_confidence")
    if extraction_confidence is not None:
        if not isinstance(extraction_confidence, (int, float)):
            errors.append(f"item={item_label}: 'extraction_confidence' expects number/null, got {type(extraction_confidence).__name__}")
        elif extraction_confidence < 0 or extraction_confidence > 1:
            errors.append(f"item={item_label}: 'extraction_confidence' out of range {extraction_confidence}")

    for key, allowed in AVM_RISK_ENUM_FIELDS.items():
        value = features.get(key)
        if value is not None and value not in allowed:
            errors.append(f"item={item_label}: '{key}' enum invalid value '{value}'")

    evidence_span = features.get("evidence_span")
    if evidence_span is not None and not isinstance(evidence_span, (str, list)):
        errors.append(f"item={item_label}: 'evidence_span' expects str/list/null, got {type(evidence_span).__name__}")

    if "evidence_source" in features:
        source = features.get("evidence_source")
        allowed_sources = {"公告", "须知", "评估报告", "页面主文"}
        if source is not None and not isinstance(source, str):
            errors.append(f"item={item_label}: 'evidence_source' expects str/null, got {type(source).__name__}")
        elif source is not None and source not in allowed_sources:
            errors.append(f"item={item_label}: 'evidence_source' invalid value '{source}'")

    extraction_version = features.get("extraction_version")
    if extraction_version is not None and not isinstance(extraction_version, str):
        errors.append(f"item={item_label}: 'extraction_version' expects str/null, got {type(extraction_version).__name__}")

    passed = len(errors) == 0
    if passed:
        logger.info(f"[AVM-RISK][SCHEMA PASS] item={item_label}")
    else:
        logger.warning(f"[AVM-RISK][SCHEMA FAILED] item={item_label}; errors={errors}")

    return passed, errors


def sanitize_avm_risk_features(features, item_id=None):
    """按字段降级清洗抽取结果，返回 (sanitized, dropped_fields)。

    与 `validate_avm_risk_features_schema` 的整条否决不同，这里把不合规的
    单个字段置为 None 并记录，其余字段原样保留。整条否决在线上造成过
    228,959 条记录风险字段全空：`orientation` 返回“东南”这类枚举外的真实值
    会把同一条里已正确抽出的 is_occupied / clear_delivery / build_year 一起
    丢掉。结构性错误（非 dict）无法字段级降级，仍整体拒绝。
    """
    item_label = item_id if item_id is not None else "unknown"

    if not isinstance(features, dict):
        logger.warning(f"[AVM-RISK][SANITIZE REJECT] item={item_label}: payload is not a dict")
        return None, []

    sanitized = dict(features)
    dropped = []

    def _drop(key, reason):
        sanitized[key] = None
        dropped.append(key)
        logger.warning(f"[AVM-RISK][FIELD DROPPED] item={item_label}: {key} ({reason})")

    for key in AVM_RISK_BOOLEAN_FIELDS:
        value = sanitized.get(key)
        if value is not None and not isinstance(value, bool):
            _drop(key, f"expects bool/null, got {type(value).__name__}")

    for key in AVM_RISK_NUMERIC_FIELDS:
        value = sanitized.get(key)
        # bool 是 int 的子类，这里要排除，否则 True 会被当成数字放过
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            _drop(key, f"expects number/null, got {type(value).__name__}")

    for key, allowed in AVM_RISK_ENUM_FIELDS.items():
        value = sanitized.get(key)
        if value is not None and value not in allowed:
            _drop(key, f"enum invalid value {value!r}")

    confidence = sanitized.get("extraction_confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            _drop("extraction_confidence", f"expects number/null, got {type(confidence).__name__}")
        elif confidence < 0 or confidence > 1:
            _drop("extraction_confidence", f"out of range {confidence}")

    evidence_span = sanitized.get("evidence_span")
    if evidence_span is not None and not isinstance(evidence_span, (str, list)):
        _drop("evidence_span", f"expects str/list/null, got {type(evidence_span).__name__}")

    if dropped:
        logger.warning(f"[AVM-RISK][SANITIZED] item={item_label}: dropped={dropped}")
    else:
        logger.info(f"[AVM-RISK][SANITIZE CLEAN] item={item_label}")

    return sanitized, dropped


def _normalize_evidence_source(value):
    allowed_sources = {"公告", "须知", "评估报告", "页面主文"}
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized in allowed_sources else "页面主文"
    if isinstance(value, list):
        for item in value:
            normalized = str(item).strip()
            if normalized in allowed_sources:
                return normalized
        return "页面主文"
    if value is None:
        return "页面主文"
    return "页面主文"


def extract_avm_risk_features(page_text, item_id=None, *, model=None):
    """
    Independent AVM risk feature extraction aligned with the frozen collection contract
    and the in-code AVM risk prompt rules.
    """
    item_label = item_id if item_id is not None else "unknown"
    if not page_text or not str(page_text).strip():
        logger.warning(f"[AVM-RISK] Empty page text for item={item_label}")
        return None

    from src.llm_request_policy import MAX_INPUT_CHARACTERS
    from src.llm_text_extraction import filter_content

    text_input = str(page_text)
    if "<" in text_input and ">" in text_input:
        text_input = filter_content(text_input)
    prompt = build_avm_risk_prompt(text_input[:MAX_INPUT_CHARACTERS])

    try:
        raw = chat_with_glm(prompt, model=model) if model else chat_with_glm(prompt)
        features = json.loads(raw)
    except Exception as e:
        logger.error(f"[AVM-RISK] LLM parse error item={item_label}: {e}")
        return None

    if not isinstance(features, dict):
        logger.warning(f"[AVM-RISK] Non-dict response item={item_label}: {type(features).__name__}")
        return None

    for key in AVM_RISK_KEYS:
        if key not in features:
            features[key] = None

    for key in AVM_RISK_AUDIT_KEYS:
        features.setdefault(key, None)

    features["extraction_version"] = features.get("extraction_version") or "avm_risk_v2"
    features["evidence_source"] = _normalize_evidence_source(features.get("evidence_source"))
    if features.get("extraction_confidence") is None:
        features["extraction_confidence"] = 0.5
    if features.get("evidence_span") is None:
        features["evidence_span"] = ""

    # 保留一次整条校验，纯粹为了把问题字段打进日志便于观测
    validate_avm_risk_features_schema(features, item_id=item_id)

    # 落库走字段级降级：坏字段置 None，好字段保留。整条否决会让单个枚举外的
    # 真实值（如 orientation="东南"）带走同一条里所有正确抽取的风险字段。
    sanitized, _dropped = sanitize_avm_risk_features(features, item_id=item_id)
    return sanitized


__all__ = ['AVM_RISK_BOOLEAN_FIELDS', 'AVM_RISK_NUMERIC_FIELDS', 'AVM_RISK_ENUM_FIELDS', 'AVM_RISK_KEYS', 'AVM_RISK_AUDIT_KEYS', 'validate_avm_risk_features_schema', 'sanitize_avm_risk_features', '_normalize_evidence_source', 'extract_avm_risk_features']
