from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .service_context import (
    GLOBAL_RECENT_CANDIDATES,
    MAX_CANDIDATE_POOL,
    MODEL_VERSION,
    RISK_IMPACT_MAP,
)
from .service_data import AVMDataMixin
from .service_health import AVMHealthMixin
from .service_prediction import AVMPredictionMixin
from .service_review import AVMReviewMixin


class AVMService(AVMDataMixin, AVMPredictionMixin, AVMHealthMixin, AVMReviewMixin):
    def __init__(self, data_dir: str = "datas", repository: Any = None) -> None:
        self.data_dir = data_dir
        self.repository = repository
        self._feature_cache: List[Dict[str, Any]] | None = None
        self._feature_cache_signature: Tuple[Tuple[str, float], ...] | None = None
        self._centroid_cache: Dict[str, Tuple[float, float]] | None = None
        self._centroid_cache_signature: Tuple[Any, ...] | None = None
        self._candidate_indexes: Dict[str, Any] | None = None
        self._candidate_indexes_signature: Tuple[Any, ...] | None = None
        self._feature_cache_hits = 0
        self._feature_cache_misses = 0
        self._predict_requests = 0
        self._evaluate_requests = 0
        self._lookup_requests = 0
        self._predict_total_ms = 0.0
        self._evaluate_total_ms = 0.0
        self._lookup_total_ms = 0.0
        self._strategy_counts: Dict[str, int] = {}
        self._quality_filtered_records = 0

    @staticmethod
    def model_version() -> str:
        return MODEL_VERSION

    @staticmethod
    def _normalize_valuation_mode(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text == "current_market":
            return "current_market"
        if text == "historical_strict":
            return "historical_strict"
        return "current_market"

    @staticmethod
    def _normalized_group_value(value: Any) -> str:
        text = str(value or "").strip()
        if not text or text == "UNK":
            return ""
        return text

    @staticmethod
    def _has_valid_coordinates(record: Dict[str, Any]) -> bool:
        lat = record.get("latitude")
        lon = record.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return False
        return 3.0 <= float(lat) <= 54.5 and 73.0 <= float(lon) <= 136.0


__all__ = [
    "AVMService",
    "MODEL_VERSION",
    "MAX_CANDIDATE_POOL",
    "GLOBAL_RECENT_CANDIDATES",
    "RISK_IMPACT_MAP",
]
