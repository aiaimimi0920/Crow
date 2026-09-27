"""Control-plane operator command HTTP handlers with live callback ownership."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol
from urllib.parse import urlparse


class ObserverCommandHandler(Protocol):
    path: str

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: dict[str, object]
    ) -> None: ...


class ObserverCommandHost(Protocol):
    def _require_control_plane(self, handler: ObserverCommandHandler) -> bool: ...
    def _read_json_body(
        self, handler: ObserverCommandHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _collection_observer_reset_region_links_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]: ...
    def _collection_observer_reanalysis_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]: ...
    def _collection_observer_manual_update_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]: ...
    def _collection_observer_runtime_control_payload(
        self, action: str
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class ObserverCommandHandlers:
    _post_region_reset_links: Callable[[ObserverCommandHandler], None]
    _post_item_reanalyze: Callable[[ObserverCommandHandler], None]
    _post_item_manual_update: Callable[[ObserverCommandHandler], None]
    _post_collection_control: Callable[[ObserverCommandHandler], None]
    __all__: ClassVar[list[str]] = [
        "_post_region_reset_links",
        "_post_item_reanalyze",
        "_post_item_manual_update",
        "_post_collection_control",
    ]


def bind_observer_commands(host: ObserverCommandHost) -> ObserverCommandHandlers:
    def _post_region_reset_links(handler: ObserverCommandHandler) -> None:
        if not host._require_control_plane(handler):
            return
        (accepted, payload) = host._read_json_body(handler)
        if not accepted:
            return
        try:
            result = host._collection_observer_reset_region_links_payload(payload)
        except Exception as e:  # noqa: BLE001 - preserve command error boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_REGION_RESET_FAILED",
                message="地区链接采集重置失败",
                details={"error": str(e)},
            )
            return
        status = 200 if result.get("ok") else 400
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_OBSERVER_REGION_RESET_REJECTED",
                message="地区链接采集重置请求被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    def _post_item_reanalyze(handler: ObserverCommandHandler) -> None:
        if not host._require_control_plane(handler):
            return
        (accepted, payload) = host._read_json_body(handler)
        if not accepted:
            return
        try:
            result = host._collection_observer_reanalysis_payload(payload)
        except Exception as e:  # noqa: BLE001 - preserve command error boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_REANALYZE_FAILED",
                message="AI 再分析入队失败",
                details={"error": str(e)},
            )
            return
        status = 200 if result.get("ok") else 400
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_OBSERVER_REANALYZE_REJECTED",
                message="AI 再分析请求被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    def _post_item_manual_update(handler: ObserverCommandHandler) -> None:
        if not host._require_control_plane(handler):
            return
        (accepted, payload) = host._read_json_body(handler)
        if not accepted:
            return
        try:
            result = host._collection_observer_manual_update_payload(payload)
        except Exception as e:  # noqa: BLE001 - preserve command error boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_MANUAL_UPDATE_FAILED",
                message="手动更新标准化数据失败",
                details={"error": str(e)},
            )
            return
        status = 200 if result.get("ok") else 400
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_OBSERVER_MANUAL_UPDATE_REJECTED",
                message="手动更新标准化数据请求被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    def _post_collection_control(handler: ObserverCommandHandler) -> None:
        if not host._require_control_plane(handler):
            return
        accepted, _payload = host._read_json_body(handler)
        if not accepted:
            return
        action = "pause" if urlparse(handler.path).path.endswith("/pause") else "resume"
        try:
            result = host._collection_observer_runtime_control_payload(action)
        except Exception as e:  # noqa: BLE001 - preserve command error boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_RUNTIME_CONTROL_FAILED",
                message="采集运行状态切换失败",
                details={"error": str(e), "action": action},
            )
            return
        status = 200 if result.get("ok") else 400
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_OBSERVER_RUNTIME_CONTROL_REJECTED",
                message="采集运行状态切换请求被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    return ObserverCommandHandlers(
        _post_region_reset_links,
        _post_item_reanalyze,
        _post_item_manual_update,
        _post_collection_control,
    )
