from __future__ import annotations

import glob
import os
from typing import Any, Dict, Iterator, List, Tuple

from src.runtime_json import load_json_file

from .canonical_mapper import map_raw_to_canonical
from .feature_builder import build_features
from .quality import price_plausibility
from .service_context import GLOBAL_RECENT_CANDIDATES


class AVMDataMixin:
    def _coordinate_group_keys(self, record: Dict[str, Any]) -> List[Tuple[str, str]]:
        community = self._normalized_group_value(record.get("community_name"))
        business_area = self._normalized_group_value(record.get("business_area"))
        district = self._normalized_group_value(record.get("district"))
        city = self._normalized_group_value(record.get("city"))

        keys: List[Tuple[str, str]] = []
        if community:
            keys.append(("community_centroid", f"community::{community}"))
        if city and district and business_area:
            keys.append(
                (
                    "business_area_centroid",
                    f"business::{city}::{district}::{business_area}",
                )
            )
        if city and district:
            keys.append(("district_centroid", f"district::{city}::{district}"))
        if city:
            keys.append(("city_centroid", f"city::{city}"))
        return keys

    def _build_coordinate_centroids(
        self, dataset: List[Dict[str, Any]]
    ) -> Dict[str, Tuple[float, float]]:
        aggregates: Dict[str, List[float]] = {}
        for record in dataset:
            if not self._has_valid_coordinates(record):
                continue

            lat = float(record["latitude"])
            lon = float(record["longitude"])
            for _, key in self._coordinate_group_keys(record):
                bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
                bucket[0] += lat
                bucket[1] += lon
                bucket[2] += 1.0

        centroids: Dict[str, Tuple[float, float]] = {}
        for key, (lat_sum, lon_sum, count) in aggregates.items():
            if count <= 0:
                continue
            centroids[key] = (round(lat_sum / count, 6), round(lon_sum / count, 6))
        return centroids

    def _enrich_coordinates(
        self, record: Dict[str, Any], centroids: Dict[str, Tuple[float, float]]
    ) -> Dict[str, Any]:
        enriched = dict(record)
        if self._has_valid_coordinates(enriched):
            enriched["coordinate_strategy"] = "observed"
            return enriched

        for strategy, key in self._coordinate_group_keys(enriched):
            centroid = centroids.get(key)
            if centroid is None:
                continue
            enriched["latitude"], enriched["longitude"] = centroid
            enriched["coordinate_strategy"] = strategy
            return enriched

        enriched["coordinate_strategy"] = "missing"
        return enriched

    def _iter_data_files(self) -> List[str]:
        candidates = glob.glob(os.path.join(self.data_dir, "*.json"))
        archive_candidates = glob.glob(
            os.path.join(self.data_dir, "archive", "**", "*.json"), recursive=True
        )
        files = candidates + archive_candidates

        skip_names = {
            "all_locations.json",
            "sniff_progress.json",
            "collected_locations.json",
            "model_config.json",
            "tuning_history.json",
            "seen_ids.json",
        }
        return [path for path in files if os.path.basename(path) not in skip_names]

    def _iter_raw_record_stream(self) -> Iterator[Dict[str, Any]]:
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                if hasattr(self.repository, "yield_flat_items"):
                    yielded_any = False
                    for item in self.repository.yield_flat_items():
                        yielded_any = True
                        if isinstance(item, dict):
                            yield item
                    if yielded_any:
                        return
                records = self.repository.iter_flat_items()
                if records:
                    for item in records:
                        if isinstance(item, dict):
                            yield item
                    return
            except Exception:
                pass
        for path in self._iter_data_files():
            try:
                data = load_json_file(path)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            yield item
            except Exception:
                continue

    def _iter_raw_records(self) -> List[Dict[str, Any]]:
        return list(self._iter_raw_record_stream())

    def _iter_feature_source_stream(self) -> Iterator[Dict[str, Any]]:
        if (
            self.repository
            and getattr(self.repository, "enabled", False)
            and hasattr(self.repository, "yield_feature_source_rows")
        ):
            try:
                if hasattr(self.repository, "yield_analysis_ready_rows"):
                    yielded_ready = False
                    for item in self.repository.yield_analysis_ready_rows():
                        yielded_ready = True
                        if isinstance(item, dict):
                            yield item
                    if yielded_ready:
                        return
                yielded_any = False
                for item in self.repository.yield_feature_source_rows():
                    yielded_any = True
                    if isinstance(item, dict):
                        yield item
                if yielded_any:
                    return
            except Exception:
                pass

        for raw in self._iter_raw_record_stream():
            try:
                yield map_raw_to_canonical(raw)
            except Exception:
                continue

    def _dataset_signature(self) -> Tuple[Any, ...]:
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                count_value, max_synced = self.repository.dataset_signature()
                if count_value > 0:
                    return ("db", count_value, max_synced)
            except Exception:
                pass
        files = self._iter_data_files()
        return tuple(
            sorted(
                (path, os.path.getmtime(path)) for path in files if os.path.exists(path)
            )
        )

    @staticmethod
    def _record_sort_key(record: Dict[str, Any]) -> Tuple[str, str]:
        return (str(record.get("auction_date") or ""), str(record.get("item_id") or ""))

    def _build_candidate_indexes(
        self, dataset: List[Dict[str, Any]], signature: Tuple[Any, ...]
    ) -> Dict[str, Any]:
        if (
            self._candidate_indexes is not None
            and self._candidate_indexes_signature == signature
        ):
            return self._candidate_indexes

        community_index: Dict[str, List[Dict[str, Any]]] = {}
        business_index: Dict[str, List[Dict[str, Any]]] = {}
        district_index: Dict[str, List[Dict[str, Any]]] = {}
        city_index: Dict[str, List[Dict[str, Any]]] = {}

        ordered = sorted(dataset, key=self._record_sort_key, reverse=True)
        for record in ordered:
            community = self._normalized_group_value(record.get("community_name"))
            business_area = self._normalized_group_value(record.get("business_area"))
            district = self._normalized_group_value(record.get("district"))
            city = self._normalized_group_value(record.get("city"))

            if community:
                community_index.setdefault(community, []).append(record)
            if city and district and business_area:
                business_index.setdefault(
                    f"{city}::{district}::{business_area}", []
                ).append(record)
            if city and district:
                district_index.setdefault(f"{city}::{district}", []).append(record)
            if city:
                city_index.setdefault(city, []).append(record)

        indexes = {
            "community": community_index,
            "business": business_index,
            "district": district_index,
            "city": city_index,
            "global_recent": ordered[:GLOBAL_RECENT_CANDIDATES],
        }
        self._candidate_indexes = indexes
        self._candidate_indexes_signature = signature
        return indexes

    def _build_feature_dataset(self) -> List[Dict[str, Any]]:
        signature = self._dataset_signature()
        if (
            self._feature_cache is not None
            and signature == self._feature_cache_signature
        ):
            self._feature_cache_hits += 1
            return list(self._feature_cache)

        self._feature_cache_misses += 1
        dataset: List[Dict[str, Any]] = []
        filtered_count = 0
        for canonical in self._iter_feature_source_stream():
            try:
                f = build_features(canonical)
            except Exception:
                continue
            passed, _ = price_plausibility(f)
            if not passed:
                filtered_count += 1
                continue
            dataset.append(f)
        centroids = self._build_coordinate_centroids(dataset)
        dataset = [self._enrich_coordinates(record, centroids) for record in dataset]
        self._feature_cache = list(dataset)
        self._feature_cache_signature = signature
        self._centroid_cache = centroids
        self._centroid_cache_signature = signature
        self._build_candidate_indexes(dataset, signature)
        self._quality_filtered_records = filtered_count
        return dataset

    def ensure_coordinate_cache(
        self, allow_file_fallback: bool = True
    ) -> Dict[str, Tuple[float, float]]:
        signature = self._dataset_signature()
        if (
            self._centroid_cache is not None
            and signature == self._centroid_cache_signature
        ):
            return dict(self._centroid_cache)

        if (
            self.repository
            and getattr(self.repository, "enabled", False)
            and hasattr(self.repository, "build_coordinate_centroids")
        ):
            try:
                centroids = self.repository.build_coordinate_centroids()
                self._centroid_cache = centroids
                self._centroid_cache_signature = signature
                if centroids:
                    return dict(centroids)
            except Exception:
                pass

        aggregates: Dict[str, List[float]] = {}
        if (
            self.repository
            and getattr(self.repository, "enabled", False)
            and hasattr(self.repository, "yield_coordinate_rows")
        ):
            try:
                for feature in self.repository.yield_coordinate_rows():
                    if not self._has_valid_coordinates(feature):
                        continue
                    lat = float(feature["latitude"])
                    lon = float(feature["longitude"])
                    for _, key in self._coordinate_group_keys(feature):
                        bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
                        bucket[0] += lat
                        bucket[1] += lon
                        bucket[2] += 1.0
            except Exception:
                aggregates = {}

        if allow_file_fallback and not aggregates:
            for raw in self._iter_raw_record_stream():
                try:
                    feature = map_raw_to_canonical(raw)
                except Exception:
                    continue
                if not self._has_valid_coordinates(feature):
                    continue
                lat = float(feature["latitude"])
                lon = float(feature["longitude"])
                for _, key in self._coordinate_group_keys(feature):
                    bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
                    bucket[0] += lat
                    bucket[1] += lon
                    bucket[2] += 1.0

        centroids: Dict[str, Tuple[float, float]] = {}
        for key, (lat_sum, lon_sum, count) in aggregates.items():
            if count <= 0:
                continue
            centroids[key] = (round(lat_sum / count, 6), round(lon_sum / count, 6))

        self._centroid_cache = centroids
        self._centroid_cache_signature = signature
        return dict(centroids)


__all__ = ["AVMDataMixin"]
