"""Compatibility analysis read routes; these do not establish product maturity."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol
from urllib.parse import parse_qs, urlparse

Record = dict[str, object]


class AnalysisReadHandler(Protocol):
    path: str

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...


class AnalysisService(Protocol):
    def predict_by_item_id(self, item_id: str) -> Record: ...
    def health_snapshot(self, *, lightweight: bool) -> Record: ...


class AnalysisRepository(Protocol):
    enabled: bool


class AnalysisClock(Protocol):
    def time(self) -> float: ...


class AnalysisReadHost(Protocol):
    AVM_SERVICE: AnalysisService
    DATA_DIR: str | Path
    DB_REPOSITORY: AnalysisRepository
    time: AnalysisClock
    logger: logging.Logger

    def _runtime_started_at(self) -> float: ...
    def _avm_operator_eval_summary(self, root: Path) -> Record: ...
    def _db_counts_snapshot(self) -> Record: ...
    def _db_data_supply_snapshot(self, hours: int) -> Record: ...
    def _db_collection_stage_snapshot(self) -> Record: ...


GetHandler = Callable[[AnalysisReadHandler, object, str, dict[str, list[str]]], None]


@dataclass(frozen=True)
class AnalysisReadHandlers:
    _get_analysis_prediction: GetHandler
    _get_analysis_health: GetHandler
    _get_collection_template: GetHandler
    __all__: ClassVar[list[str]] = [
        "_get_analysis_prediction",
        "_get_analysis_health",
        "_get_collection_template",
    ]


def bind_analysis_reads(host: AnalysisReadHost) -> AnalysisReadHandlers:
    def _get_analysis_prediction(
        handler: AnalysisReadHandler,
        parsed: object,
        request_path: str,
        query: dict[str, list[str]],
    ) -> None:
        params = parse_qs(urlparse(handler.path).query)
        item_id = (params.get("id", [""])[0] or "").strip()
        if not item_id:
            handler.send_error_json(
                status=400,
                code="AVM_INVALID_ID",
                message="缺少必填参数 id",
                details={"required": ["id"]},
            )
            return
        try:
            result = host.AVM_SERVICE.predict_by_item_id(item_id)
            if result.get("error") == "item_not_found":
                handler.send_error_json(
                    status=404,
                    code="AVM_NOT_FOUND",
                    message=f"ID={item_id} 不存在",
                    details={"id": item_id},
                )
                return
            handler.send_json(result)
        except Exception as e:
            host.logger.exception("AVM prediction failed item=%s", item_id)
            handler.send_error_json(
                status=500,
                code="AVM_PREDICT_FAILED",
                message="估值失败",
                details={"error": str(e), "id": str(item_id)},
            )

    def _get_analysis_health(
        handler: AnalysisReadHandler,
        parsed: object,
        request_path: str,
        query: dict[str, list[str]],
    ) -> None:
        try:
            uptime_sec = max(0, int(host.time.time() - host._runtime_started_at()))
            service_stats = host.AVM_SERVICE.health_snapshot(lightweight=True)
            summary = host._avm_operator_eval_summary(
                Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
            )
            db_stats: Record = {
                "db_mode": host.DB_REPOSITORY.enabled,
                "db_total_ids": None,
                "db_processed_ids": None,
                "db_pending_ids": None,
                "db_detail_captured_ids": None,
            }
            if host.DB_REPOSITORY.enabled:
                try:
                    db_stats.update(host._db_counts_snapshot())
                except Exception as db_health_error:  # noqa: BLE001 - preserve degraded health response
                    db_stats["db_error"] = str(db_health_error)
            handler.send_json(
                {
                    "status": "ok",
                    "service": "avm",
                    "uptime_sec": uptime_sec,
                    **service_stats,
                    **summary,
                    **db_stats,
                    "data_supply_recent_24h": host._db_data_supply_snapshot(24)
                    if host.DB_REPOSITORY.enabled
                    else {},
                    "collection_stage": host._db_collection_stage_snapshot(),
                }
            )
        except Exception as e:  # noqa: BLE001 - preserve HTTP health boundary
            handler.send_error_json(
                status=500,
                code="AVM_HEALTH_FAILED",
                message="健康概览生成失败",
                details={"error": str(e)},
            )

    def _get_collection_template(
        handler: AnalysisReadHandler,
        parsed: object,
        request_path: str,
        query: dict[str, list[str]],
    ) -> None:
        from .avm.collection_template import get_collection_template

        try:
            handler.send_json(get_collection_template())
        except Exception as e:  # noqa: BLE001 - preserve HTTP template boundary
            handler.send_error_json(
                status=500,
                code="AVM_COLLECTION_TEMPLATE_FAILED",
                message="collection template 生成失败",
                details={"error": str(e)},
            )

    return AnalysisReadHandlers(
        _get_analysis_prediction, _get_analysis_health, _get_collection_template
    )
