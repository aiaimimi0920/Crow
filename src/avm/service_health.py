from __future__ import annotations

from typing import Any, Dict, List

from src.avm_config import get_effective_risk_discount_factor, get_effective_weighting

from .engine import get_active_risk_factor_overrides
from .service_context import MAX_CANDIDATE_POOL, MODEL_VERSION


class AVMHealthMixin:
    def _summarize_dataset(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        observed = 0
        centroid_filled = 0
        missing = 0
        coordinate_strategy_counts: Dict[str, int] = {}
        risk_validation_counts = {"ok": 0, "incomplete": 0, "invalid": 0}
        risk_feature_completeness_total = 0.0
        for record in dataset:
            strategy = record.get("coordinate_strategy")
            strategy_key = str(strategy or "missing")
            coordinate_strategy_counts[strategy_key] = (
                coordinate_strategy_counts.get(strategy_key, 0) + 1
            )
            if strategy == "observed":
                observed += 1
            elif strategy == "missing":
                missing += 1
            else:
                centroid_filled += 1
            risk_validation = self._build_risk_validation(record)
            if risk_validation["invalid_field_count"] > 0:
                risk_validation_counts["invalid"] += 1
            elif risk_validation["ok"]:
                risk_validation_counts["ok"] += 1
            else:
                risk_validation_counts["incomplete"] += 1
            risk_feature_completeness_total += float(
                risk_validation["feature_completeness"]
            )
        return {
            "dataset_size": len(dataset),
            "coordinate_observed": observed,
            "coordinate_centroid_filled": centroid_filled,
            "coordinate_missing": missing,
            "coordinate_strategy_counts": dict(
                sorted(coordinate_strategy_counts.items())
            ),
            "risk_validation_counts": risk_validation_counts,
            "risk_feature_completeness_avg": round(
                risk_feature_completeness_total / max(len(dataset), 1),
                4,
            ),
        }

    def health_snapshot(self, lightweight: bool = False) -> Dict[str, Any]:
        dataset_summary = {
            "dataset_size": 0,
            "coordinate_observed": 0,
            "coordinate_centroid_filled": 0,
            "coordinate_missing": 0,
            "coordinate_strategy_counts": {},
            "risk_validation_counts": {"ok": 0, "incomplete": 0, "invalid": 0},
            "risk_feature_completeness_avg": 0.0,
        }
        feature_cache_ready = self._feature_cache is not None
        if self._feature_cache is not None:
            dataset_summary = self._summarize_dataset(self._feature_cache)
        elif not lightweight:
            dataset = self._build_feature_dataset()
            dataset_summary = self._summarize_dataset(dataset)
            feature_cache_ready = self._feature_cache is not None

        return {
            **dataset_summary,
            "analysis_ready_count": self.repository.count_analysis_ready_items()
            if self.repository
            and getattr(self.repository, "enabled", False)
            and hasattr(self.repository, "count_analysis_ready_items")
            else 0,
            "centroid_bucket_count": len(self._centroid_cache or {}),
            "candidate_index_ready": self._candidate_indexes is not None,
            "candidate_index_bucket_count": sum(
                len(index_map)
                for index_map in (
                    (self._candidate_indexes or {}).get("community", {}),
                    (self._candidate_indexes or {}).get("business", {}),
                    (self._candidate_indexes or {}).get("district", {}),
                    (self._candidate_indexes or {}).get("city", {}),
                )
            ),
            "candidate_pool_limit": MAX_CANDIDATE_POOL,
            "model_version": MODEL_VERSION,
            "feature_cache_ready": feature_cache_ready,
            "feature_cache_hits": self._feature_cache_hits,
            "feature_cache_misses": self._feature_cache_misses,
            "feature_cache_hit_rate": round(
                self._feature_cache_hits
                / max(self._feature_cache_hits + self._feature_cache_misses, 1),
                4,
            ),
            "predict_requests": self._predict_requests,
            "evaluate_requests": self._evaluate_requests,
            "lookup_requests": self._lookup_requests,
            "avg_predict_time_ms": round(
                self._predict_total_ms / max(self._predict_requests, 1), 2
            ),
            "avg_evaluate_time_ms": round(
                self._evaluate_total_ms / max(self._evaluate_requests, 1), 2
            ),
            "avg_lookup_time_ms": round(
                self._lookup_total_ms / max(self._lookup_requests, 1), 2
            ),
            "strategy_counts": dict(sorted(self._strategy_counts.items())),
            "quality_filtered_records": self._quality_filtered_records,
            "active_weighting": get_effective_weighting(),
            "active_risk_discount_factor": get_effective_risk_discount_factor(0.9),
            "active_risk_factor_override_count": len(
                get_active_risk_factor_overrides()
            ),
            "active_risk_factor_overrides": get_active_risk_factor_overrides(),
        }


__all__ = ["AVMHealthMixin"]
