from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .canonical_mapper import map_raw_to_canonical
from .engine import predict_fair_price
from .feature_builder import build_features
from .service_context import MAX_CANDIDATE_POOL


class AVMPredictionMixin:
    def _candidate_pool(
        self,
        subject: Dict[str, Any],
        dataset: List[Dict[str, Any]],
        signature: Tuple[Any, ...],
    ) -> List[Dict[str, Any]]:
        if len(dataset) <= MAX_CANDIDATE_POOL:
            return dataset

        indexes = self._build_candidate_indexes(dataset, signature)
        candidates: Dict[str, Dict[str, Any]] = {}

        community = self._normalized_group_value(subject.get("community_name"))
        business_area = self._normalized_group_value(subject.get("business_area"))
        district = self._normalized_group_value(subject.get("district"))
        city = self._normalized_group_value(subject.get("city"))

        def _extend(records: Iterable[Dict[str, Any]]) -> None:
            for record in records:
                candidates[str(record.get("item_id"))] = record

        if community:
            _extend(indexes["community"].get(community, []))
        if city and district and business_area:
            _extend(indexes["business"].get(f"{city}::{district}::{business_area}", []))
        if city and district:
            _extend(indexes["district"].get(f"{city}::{district}", []))
        if city:
            _extend(indexes["city"].get(city, []))
        if len(candidates) < MAX_CANDIDATE_POOL:
            _extend(indexes["global_recent"])

        ordered = sorted(candidates.values(), key=self._record_sort_key, reverse=True)
        return ordered[:MAX_CANDIDATE_POOL]

    def predict_by_item_data(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        self._predict_requests += 1
        started = time.perf_counter()
        signature = self._dataset_signature()
        if self._centroid_cache is None:
            self.ensure_coordinate_cache(
                allow_file_fallback=not bool(
                    self.repository and getattr(self.repository, "enabled", False)
                )
            )
        subject = build_features(map_raw_to_canonical(item_data))
        subject["valuation_mode"] = self._normalize_valuation_mode(
            item_data.get("valuation_mode")
        )
        subject = self._enrich_coordinates(subject, self._centroid_cache or {})
        candidate_dataset: List[Dict[str, Any]] = []
        candidate_source = "feature_cache"

        if self.repository and getattr(self.repository, "enabled", False):
            try:
                if hasattr(self.repository, "iter_analysis_candidate_rows"):
                    repo_rows = self.repository.iter_analysis_candidate_rows(
                        subject,
                        total_limit=MAX_CANDIDATE_POOL,
                    )
                elif hasattr(self.repository, "iter_feature_candidate_rows"):
                    repo_rows = self.repository.iter_feature_candidate_rows(
                        subject,
                        total_limit=MAX_CANDIDATE_POOL,
                    )
                else:
                    repo_rows = []
            except Exception:
                repo_rows = []
            if repo_rows:
                candidate_source = (
                    "repository_analysis_candidates"
                    if hasattr(self.repository, "iter_analysis_candidate_rows")
                    else "repository_candidates"
                )
                candidate_dataset = [build_features(row) for row in repo_rows]

        if not candidate_dataset:
            dataset = self._build_feature_dataset()
            candidate_dataset = self._candidate_pool(subject, dataset, signature)

        comparable_dataset = [
            record
            for record in candidate_dataset
            if str(record.get("item_id")) != str(subject.get("item_id"))
        ]
        result = predict_fair_price(subject, comparable_dataset)
        result["risk_validation"] = self._public_risk_validation_payload(
            self._build_risk_validation(subject)
        )
        result["item_id"] = str(subject.get("item_id"))
        result["id"] = str(subject.get("item_id"))
        result.setdefault("trace", {})
        result["trace"]["subject_coordinate_strategy"] = subject.get(
            "coordinate_strategy", "missing"
        )
        result["trace"]["candidate_source"] = candidate_source
        self._attach_manual_review(subject, result)
        strategy = str(result.get("strategy") or "unknown")
        self._strategy_counts[strategy] = self._strategy_counts.get(strategy, 0) + 1

        starting_price = subject.get("starting_price")
        predicted_price = result.get("predicted_price")
        if starting_price and predicted_price:
            try:
                result["margin_of_safety"] = round(
                    (float(predicted_price) - float(starting_price))
                    / float(predicted_price),
                    4,
                )
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        result.setdefault("trace", {})
        result["trace"]["candidate_pool_size"] = len(candidate_dataset)
        self._predict_total_ms += (time.perf_counter() - started) * 1000
        return result

    def predict_by_item_id(self, item_id: str) -> Dict[str, Any]:
        self._lookup_requests += 1
        started = time.perf_counter()
        subject: Optional[Dict[str, Any]] = None
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                subject = self.repository.get_flat_item(str(item_id))
            except Exception:
                subject = None
        if subject is None:
            for raw in self._iter_raw_record_stream():
                raw_id = raw.get("id") or raw.get("唯一id") or raw.get("item_id")
                if str(raw_id) == str(item_id):
                    subject = raw
                    break
        if not subject:
            self._lookup_total_ms += (time.perf_counter() - started) * 1000
            return {"error": "item_not_found", "item_id": str(item_id)}
        result = self.predict_by_item_data(subject)
        self._lookup_total_ms += (time.perf_counter() - started) * 1000
        return result


__all__ = ["AVMPredictionMixin"]
