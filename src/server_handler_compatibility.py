"""Native HTTP method adapters for compatibility writes and diagnostics."""

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, Protocol
from urllib.parse import urlparse


class CompatibilityHandler(Protocol):
    path: str

    def send_json(self, data: object) -> None: ...
    def send_response(self, code: int) -> None: ...
    def end_headers(self) -> None: ...


class HandlerCompatibilityHost(Protocol):
    logger: Logger

    def update_file_global(
        self, file_path: str, item_id: str, new_data: dict[str, object]
    ) -> object: ...
    def _read_json_body(
        self, handler: CompatibilityHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _send_guard_error(
        self, handler: CompatibilityHandler, error: dict[str, object]
    ) -> object: ...


@dataclass(frozen=True)
class HandlerCompatibility:
    update_file: Callable[..., None]
    log_message: Callable[..., None]
    _post_client_log: Callable[[CompatibilityHandler], None]
    _server_post_fallback: Callable[[CompatibilityHandler], None]
    __all__: ClassVar[list[str]] = [
        "update_file",
        "log_message",
        "_post_client_log",
        "_server_post_fallback",
    ]


def bind_handler_compatibility(host: HandlerCompatibilityHost) -> HandlerCompatibility:
    def update_file(
        handler: object, file_path: str, item_id: str, new_data: dict[str, object]
    ) -> None:
        host.update_file_global(file_path, item_id, new_data)

    def log_message(handler: object, format: str, *args: object) -> None:
        return

    def _post_client_log(handler: CompatibilityHandler) -> None:
        accepted, data = host._read_json_body(handler)
        if not accepted:
            return
        message = str(data.get("msg", ""))[:4000]
        is_error = data.get("isError", False)
        prefix = "[Client Error]" if is_error else "[Client Log]"
        (host.logger.error if is_error else host.logger.info)("%s %s", prefix, message)
        handler.send_json({"status": "ok"})

    def _server_post_fallback(handler: CompatibilityHandler) -> None:
        request_path = urlparse(handler.path).path
        if request_path.startswith("/api/"):
            host._send_guard_error(
                handler,
                {
                    "status": 404,
                    "code": "AVM_ENDPOINT_NOT_FOUND",
                    "message": "未找到接口",
                    "details": {"path": request_path},
                },
            )
        else:
            handler.send_response(404)
            handler.end_headers()

    return HandlerCompatibility(
        update_file, log_message, _post_client_log, _server_post_fallback
    )
