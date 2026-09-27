"""Legacy evaluation and location inference admission with native ownership."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol

from .location_inference_handlers import LocationHandler as EvaluationHandler
from .location_inference_handlers import LocationHost, bind_location_inference

Record = dict[str, object]


class EvaluationService(Protocol):
    def evaluate_request(self, payload: Record) -> object: ...


class EvaluationHost(LocationHost, Protocol):
    AVM_SERVICE: EvaluationService


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
    location = bind_location_inference(host)
    _read_execution_mode = location._read_execution_mode
    _post_infer_location = location._post_infer_location

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

    return EvaluationHandlers(
        _read_execution_mode, _post_analysis_evaluate, _post_infer_location
    )
