"""Public imports for Crow's native LLM backends and extraction helpers."""

from __future__ import annotations

from src.llm_auction_extraction import (
    AVM_RISK_PROMPT_OUTPUT_RULE as AVM_RISK_PROMPT_OUTPUT_RULE,
)
from src.llm_auction_extraction import (
    AVM_RISK_PROMPT_RULES as AVM_RISK_PROMPT_RULES,
)
from src.llm_auction_extraction import (
    AVM_RISK_SYSTEM_PROMPT as AVM_RISK_SYSTEM_PROMPT,
)
from src.llm_auction_extraction import (
    _extract_avm_risk_features_raw as _extract_avm_risk_features_raw,
)
from src.llm_auction_extraction import (
    build_avm_risk_prompt as build_avm_risk_prompt,
)
from src.llm_auction_extraction import (
    extract_auction_data as extract_auction_data,
)
from src.llm_avm_risk import (
    AVM_RISK_AUDIT_KEYS as AVM_RISK_AUDIT_KEYS,
)
from src.llm_avm_risk import (
    AVM_RISK_BOOLEAN_FIELDS as AVM_RISK_BOOLEAN_FIELDS,
)
from src.llm_avm_risk import (
    AVM_RISK_ENUM_FIELDS as AVM_RISK_ENUM_FIELDS,
)
from src.llm_avm_risk import (
    AVM_RISK_KEYS as AVM_RISK_KEYS,
)
from src.llm_avm_risk import (
    AVM_RISK_NUMERIC_FIELDS as AVM_RISK_NUMERIC_FIELDS,
)
from src.llm_avm_risk import (
    _normalize_evidence_source as _normalize_evidence_source,
)
from src.llm_avm_risk import (
    extract_avm_risk_features as extract_avm_risk_features,
)
from src.llm_avm_risk import (
    sanitize_avm_risk_features as sanitize_avm_risk_features,
)
from src.llm_avm_risk import (
    validate_avm_risk_features_schema as validate_avm_risk_features_schema,
)
from src.llm_config import (
    _SECRETS_FILE as _SECRETS_FILE,
)
from src.llm_config import (
    CONFIG_FILE as CONFIG_FILE,
)
from src.llm_config import (
    _build_model_pool as _build_model_pool,
)
from src.llm_config import (
    _has_openai_compatible_env as _has_openai_compatible_env,
)
from src.llm_config import (
    _load_secrets as _load_secrets,
)
from src.llm_config import (
    get_model_pool as get_model_pool,
)
from src.llm_config import (
    load_model_config as load_model_config,
)
from src.llm_metrics import (
    API_METRICS as API_METRICS,
)
from src.llm_metrics import (
    API_METRICS_LOCK as API_METRICS_LOCK,
)
from src.llm_metrics import (
    PREDICTION_LOG_DIR as PREDICTION_LOG_DIR,
)
from src.llm_metrics import (
    PREDICTION_LOG_LOCK as PREDICTION_LOG_LOCK,
)
from src.llm_metrics import (
    _daily_prediction_log_path as _daily_prediction_log_path,
)
from src.llm_metrics import (
    _utc_now as _utc_now,
)
from src.llm_metrics import (
    get_api_metrics as get_api_metrics,
)
from src.llm_metrics import (
    log_prediction_event as log_prediction_event,
)
from src.llm_metrics import (
    record_api_metrics as record_api_metrics,
)
from src.llm_model_selector import (
    AUTH_INVALID_ERROR_CODES as AUTH_INVALID_ERROR_CODES,
)
from src.llm_model_selector import (
    LLMBackendUnavailableError as LLMBackendUnavailableError,
)
from src.llm_model_selector import (
    ModelSelector as ModelSelector,
)
from src.llm_model_selector import (
    get_model_for_task as get_model_for_task,
)
from src.llm_model_selector import (
    get_model_selector as get_model_selector,
)
from src.llm_openai_compatible import (
    _chat_with_openai_compatible as _chat_with_openai_compatible,
)
from src.llm_openai_compatible import (
    _first_nonempty_env as _first_nonempty_env,
)
from src.llm_openai_compatible import (
    _get_openai_compatible_config as _get_openai_compatible_config,
)
from src.llm_openai_compatible import (
    _get_openai_compatible_proxies as _get_openai_compatible_proxies,
)
from src.llm_openai_compatible import (
    _is_local_openai_compatible_url as _is_local_openai_compatible_url,
)
from src.llm_openai_compatible import (
    _strip_json_markdown as _strip_json_markdown,
)
from src.llm_openai_compatible import (
    chat_with_glm as chat_with_glm,
)
from src.llm_openai_compatible import (
    preflight_llm_backend as preflight_llm_backend,
)
from src.llm_openai_compatible import (
    preflight_openai_compatible_backend as preflight_openai_compatible_backend,
)
from src.llm_openai_compatible import (
    require_non_gpt_analysis_model as require_non_gpt_analysis_model,
)
from src.llm_product_extraction import (
    build_product_extraction_prompt as build_product_extraction_prompt,
)
from src.llm_product_extraction import (
    extract_product_data as extract_product_data,
)
from src.llm_text_extraction import (
    AREA_EVIDENCE_PATTERNS as AREA_EVIDENCE_PATTERNS,
)
from src.llm_text_extraction import (
    COORDINATE_PATTERNS as COORDINATE_PATTERNS,
)
from src.llm_text_extraction import (
    GENERIC_AREA_EVIDENCE_PATTERNS as GENERIC_AREA_EVIDENCE_PATTERNS,
)
from src.llm_text_extraction import (
    NON_BUILDING_AREA_PREFIXES as NON_BUILDING_AREA_PREFIXES,
)
from src.llm_text_extraction import (
    _backfill_area_and_unit_price as _backfill_area_and_unit_price,
)
from src.llm_text_extraction import (
    _decode_response_bytes as _decode_response_bytes,
)
from src.llm_text_extraction import (
    _is_valid_china_coordinate as _is_valid_china_coordinate,
)
from src.llm_text_extraction import (
    _parse_area_number as _parse_area_number,
)
from src.llm_text_extraction import (
    _parse_description_data_link as _parse_description_data_link,
)
from src.llm_text_extraction import (
    _parse_plain_number as _parse_plain_number,
)
from src.llm_text_extraction import (
    _parse_share_ratio as _parse_share_ratio,
)
from src.llm_text_extraction import (
    extract_area_from_text as extract_area_from_text,
)
from src.llm_text_extraction import (
    extract_property_coordinates as extract_property_coordinates,
)
from src.llm_text_extraction import (
    fetch_description_data_text as fetch_description_data_text,
)
from src.llm_text_extraction import (
    filter_content as filter_content,
)
from src.llm_websocket import AIService as AIService
from src.llm_websocket import Ws_Param as Ws_Param

if __name__ == "__main__":
    print("Testing GLM-4.7 (WebSocket)...")
    response = chat_with_glm(
        '你好，请做一个简单的自我介绍，并返回JSON格式: {"name": "AI", "role": "Assistant"}'
    )
    print(f"Response: {response}")
