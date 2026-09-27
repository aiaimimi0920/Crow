"""Legacy evaluation and location inference admission with native ownership."""

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, Protocol

Record = dict[str, object]


class EvaluationHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...
    def _enqueue_collection_job(
        self,
        kind: str,
        work: Callable[[], object],
        error_code: str,
        *,
        response_extra: Record,
    ) -> object: ...


class EvaluationService(Protocol):
    def evaluate_request(self, payload: Record) -> object: ...


class LocationService(Protocol):
    def infer_location(
        self,
        *,
        address: object,
        title: object,
        item_id: object,
        chat_with_glm: Callable[..., object],
        log_prediction_event: Callable[..., object],
    ) -> object: ...


class LocationHelper(Protocol):
    chat_with_glm: Callable[..., object]
    log_prediction_event: Callable[..., object]


class EvaluationHost(Protocol):
    AVM_SERVICE: EvaluationService
    llm_helper: LocationHelper
    logger: Logger

    def _read_json_body(self, handler: EvaluationHandler) -> tuple[bool, Record]: ...
    def _read_execution_mode(
        self, handler: EvaluationHandler, payload: Record
    ) -> str | None: ...
    def _detail_collection_service(self) -> LocationService: ...


@dataclass(frozen=True)
class EvaluationHandlers:
    _read_execution_mode: Callable[[EvaluationHandler, Record], str | None]
    _post_analysis_evaluate: Callable[[EvaluationHandler], None]
    _post_infer_location: Callable[[EvaluationHandler], None]
    __all__: ClassVar[list[str]] = [
        "_read_execution_mode",
        "_post_analysis_evaluate",
        "_post_infer_location",
    ]


def bind_evaluations(host: EvaluationHost) -> EvaluationHandlers:
    def _read_execution_mode(self: EvaluationHandler, payload: Record) -> str | None:
        raw_execution_mode = payload.get("execution_mode", "sync")
        if not isinstance(
            raw_execution_mode, str
        ) or raw_execution_mode.strip().lower() not in {"sync", "async"}:
            self.send_error_json(
                status=400,
                code="AVM_INVALID_EXECUTION_MODE",
                message="execution_mode must be 'sync' or 'async'",
                details={"allowed": ["sync", "async"]},
            )
            return None
        return raw_execution_mode.strip().lower()

    def _post_analysis_evaluate(self: EvaluationHandler) -> None:
        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        execution_mode = host._read_execution_mode(self, payload)
        if execution_mode is None:
            return
        subject = payload.get("subject")
        if not isinstance(subject, dict) or not subject:
            self.send_error_json(
                status=400,
                code="AVM_INVALID_SUBJECT",
                message="缺少 subject 对象",
                details={"required": ["subject"]},
            )
            return
        if subject.get("area_sqm") in (None, ""):
            self.send_error_json(
                status=400,
                code="AVM_MISSING_AREA",
                message="subject.area_sqm 为必填",
                details={"required": ["subject.area_sqm"]},
            )
            return
        evaluation_payload = dict(payload)
        evaluation_payload.pop("execution_mode", None)
        service = host.AVM_SERVICE
        if execution_mode == "async":

            def work() -> object:
                return service.evaluate_request(evaluation_payload)

            response_extra: Record = {"execution_mode": "async"}
            if "request_id" in evaluation_payload:
                response_extra["request_id"] = evaluation_payload["request_id"]
            self._enqueue_collection_job(
                "avm_evaluate",
                work,
                "AVM_EVALUATE_ASYNC_FAILED",
                response_extra=response_extra,
            )
            return
        try:
            result = service.evaluate_request(evaluation_payload)
        except Exception as error:
            host.logger.exception("[AVM] Evaluate failed")
            self.send_error_json(
                status=500,
                code="AVM_EVALUATE_FAILED",
                message="评估失败",
                details={"error": str(error)},
            )
            return
        self.send_json(result)

    def _post_infer_location(self: EvaluationHandler) -> None:
        accepted, data = host._read_json_body(self)
        if not accepted:
            return
        execution_mode = host._read_execution_mode(self, data)
        if execution_mode is None:
            return
        try:
            address = data.get("address", "")
            title = data.get("title", "")
            item_id = data.get("id")
            host.logger.info("[Infer Location] Request for: %s | %s", address, title)
            service = host._detail_collection_service()
            chat_with_glm = host.llm_helper.chat_with_glm
            log_prediction_event = host.llm_helper.log_prediction_event
            if execution_mode == "async":

                def work() -> object:
                    return service.infer_location(
                        address=address,
                        title=title,
                        item_id=item_id,
                        chat_with_glm=chat_with_glm,
                        log_prediction_event=log_prediction_event,
                    )

                response_extra: Record = {"execution_mode": "async"}
                if "id" in data:
                    response_extra["item_id"] = item_id
                self._enqueue_collection_job(
                    "infer_location",
                    work,
                    "AVM_DETAIL_INFER_LOCATION_ASYNC_FAILED",
                    response_extra=response_extra,
                )
                return
            result = service.infer_location(
                address=address,
                title=title,
                item_id=item_id,
                chat_with_glm=chat_with_glm,
                log_prediction_event=log_prediction_event,
            )
            self.send_json(result)
        except Exception as error:
            host.logger.exception("Error in infer_location")
            self.send_error_json(
                status=500,
                code="AVM_DETAIL_INFER_LOCATION_FAILED",
                message="位置推断失败",
                details={"error": str(error)},
            )

    return EvaluationHandlers(
        _read_execution_mode, _post_analysis_evaluate, _post_infer_location
    )
