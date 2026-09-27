"""Legacy screening admission and execution; not a completed analysis engine."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import ClassVar, Protocol, cast

Record = dict[str, object]


class ScreenHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...
    def _enqueue_collection_job(
        self,
        kind: str,
        work: Callable[[], Record],
        error_code: str,
        *,
        response_extra: Record,
    ) -> object: ...


class ScreenIndex(Protocol):
    def get_seen(self, item_id: str) -> Record | None: ...


class ScreenRepository(Protocol):
    enabled: bool

    def get_flat_item(self, item_id: str) -> Record | None: ...


class ScreenAnalysis(Protocol):
    def predict_by_item_data(self, data: Record) -> Record: ...
    def model_version(self) -> str: ...


class ScreenHost(Protocol):
    DEFAULT_MARGIN_THRESHOLD: float
    DB_REPOSITORY: ScreenRepository
    AVM_SERVICE: ScreenAnalysis
    logger: Logger

    def _collection_runtime_index(self) -> ScreenIndex: ...
    def get_effective_alert_threshold(self, fallback: float) -> float: ...
    def build_avm_result(self, item_id: str, data: Record) -> Record: ...
    def build_alert_blockers(
        self,
        *,
        margin: object,
        threshold: float,
        is_malignant_risk: bool,
        payload: Record,
    ) -> list[str]: ...
    def _utc_now(self) -> datetime: ...
    def write_avm_alerts(self, alerts: list[Record]) -> object: ...
    def summarize_screen_results(self, results: list[Record]) -> Record: ...
    def _require_control_plane(self, handler: ScreenHandler) -> bool: ...
    def _read_json_body(self, handler: ScreenHandler) -> tuple[bool, Record]: ...
    def _read_execution_mode(
        self, handler: ScreenHandler, payload: Record
    ) -> str | None: ...
    def _run_analysis_screen(self, payload: Record) -> Record: ...


@dataclass(frozen=True)
class ScreenHandlers:
    _run_analysis_screen: Callable[[Record], Record]
    _post_analysis_screen: Callable[[ScreenHandler], None]
    __all__: ClassVar[list[str]] = ["_run_analysis_screen", "_post_analysis_screen"]


def bind_screen(host: ScreenHost) -> ScreenHandlers:
    def _run_analysis_screen(payload: Record) -> Record:
        runtime_index = host._collection_runtime_index()
        items = cast(Iterable[object], payload.get("items", []))
        raw_threshold = payload.get("margin_threshold")
        try:
            if raw_threshold is None:
                threshold = host.get_effective_alert_threshold(
                    host.DEFAULT_MARGIN_THRESHOLD
                )
            else:
                threshold = float(cast("str | float", raw_threshold))
        except Exception:  # noqa: BLE001 - preserve configured threshold fallback
            threshold = host.get_effective_alert_threshold(
                host.DEFAULT_MARGIN_THRESHOLD
            )
        results = []
        for raw in items:
            if isinstance(raw, dict):
                item_id = str(raw.get("id", "")).strip()
            else:
                item_id = str(raw).strip()
            if not item_id:
                continue
            entry = runtime_index.get_seen(item_id)
            if entry is None and host.DB_REPOSITORY.enabled:
                try:
                    db_item = host.DB_REPOSITORY.get_flat_item(item_id)
                except Exception:
                    host.logger.exception(
                        "[DB] screen item lookup failed item=%s", item_id
                    )
                    db_item = None
                if db_item and entry is None:
                    entry = {"data": db_item}
            source_data = dict(cast(Record, entry.get("data", {}))) if entry else {}
            if isinstance(raw, dict):
                source_data.update(raw)
            try:
                prediction = host.AVM_SERVICE.predict_by_item_data(source_data)
            except Exception:  # noqa: BLE001 - preserve prediction degradation
                prediction = {}
            if prediction.get("predicted_price") is not None:
                source_data["predicted_price"] = prediction.get("predicted_price")
                source_data["predicted_unit_price"] = prediction.get(
                    "predicted_unit_price"
                )
                source_data["prediction"] = prediction
            result = host.build_avm_result(item_id, source_data)
            if prediction:
                result["prediction"] = prediction
                result["risk_validation"] = dict(
                    cast(Record, prediction.get("risk_validation") or {})
                )
                result["manual_review_recommended"] = bool(
                    prediction.get("manual_review_recommended")
                )
                result["manual_review_reasons"] = list(
                    cast(
                        Iterable[object], prediction.get("manual_review_reasons") or []
                    )
                )
            else:
                result["risk_validation"] = {}
                result["manual_review_recommended"] = False
                result["manual_review_reasons"] = []
            blockers = host.build_alert_blockers(
                margin=result.get("margin"),
                threshold=threshold,
                is_malignant_risk=bool(result.get("is_malignant_risk")),
                payload=prediction,
            )
            result["alert_blockers"] = blockers
            result["meets_alert_threshold"] = len(blockers) == 0
            results.append(result)
        results.sort(
            key=lambda result: (
                cast(float, result.get("margin"))
                if result.get("margin") is not None
                else -999
            ),
            reverse=True,
        )
        alerts = []
        now = host._utc_now().strftime("%Y-%m-%d %H:%M:%S")
        for result in results:
            if result["meets_alert_threshold"]:
                alert = dict(result)
                alert["created_at"] = now
                alert["margin_threshold"] = threshold
                alerts.append(alert)
        host.write_avm_alerts(alerts)
        summary = host.summarize_screen_results(results)
        return {
            "model_version": host.AVM_SERVICE.model_version(),
            "margin_formula": "(predicted_price - starting_price) / predicted_price",
            "margin_threshold": threshold,
            "total": len(results),
            "alerts_written": len(alerts),
            "summary": summary,
            "results": results,
        }

    def _post_analysis_screen(self: ScreenHandler) -> None:
        if not host._require_control_plane(self):
            return
        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        execution_mode = host._read_execution_mode(self, payload)
        if execution_mode is None:
            return
        items = payload.get("items", [])
        if not isinstance(items, list):
            self.send_error_json(
                status=400,
                code="AVM_INVALID_SCREEN_ITEMS",
                message="items 必须为数组",
                details={"invalid_fields": ["items"]},
            )
            return
        screen_payload = dict(payload)
        screen_payload.pop("execution_mode", None)
        if execution_mode == "async":

            def work() -> Record:
                return host._run_analysis_screen(screen_payload)

            self._enqueue_collection_job(
                "avm_screen",
                work,
                "AVM_SCREEN_ASYNC_FAILED",
                response_extra={"execution_mode": "async"},
            )
            return
        try:
            self.send_json(host._run_analysis_screen(screen_payload))
        except Exception as error:  # noqa: BLE001 - preserve synchronous screen error boundary
            self.send_error_json(
                status=500,
                code="AVM_SCREEN_FAILED",
                message="批量筛选执行失败",
                details={"error": str(error)},
            )

    return ScreenHandlers(_run_analysis_screen, _post_analysis_screen)
