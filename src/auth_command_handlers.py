"""Authentication operator HTTP commands with live trust and state callbacks."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol


class AuthCommandHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: dict[str, object]
    ) -> None: ...


class AuthCommandHost(Protocol):
    def _require_node_auth(self, handler: AuthCommandHandler) -> bool: ...
    def _read_json_body(
        self, handler: AuthCommandHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _force_reset_solver_scope(
        self, scope: object, challenge_id: object
    ) -> dict[str, object]: ...
    def _cdp_endpoint_permitted(self, endpoint: object) -> bool: ...
    def _resolve_auth_cookie_snapshot_path(
        self, payload: dict[str, object]
    ) -> object: ...
    def _collection_observer_auth_complete_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]: ...
    def _collection_observer_resume_after_cooldown_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class AuthCommandHandlers:
    _post_auth_force_reset: Callable[[AuthCommandHandler], None]
    _post_auth_complete: Callable[[AuthCommandHandler], None]
    _post_auth_resume_after_cooldown: Callable[[AuthCommandHandler], None]
    __all__: ClassVar[list[str]] = [
        "_post_auth_force_reset",
        "_post_auth_complete",
        "_post_auth_resume_after_cooldown",
    ]


def bind_auth_commands(host: AuthCommandHost) -> AuthCommandHandlers:
    def _post_auth_force_reset(handler: AuthCommandHandler) -> None:
        if not host._require_node_auth(handler):
            return
        accepted, payload = host._read_json_body(handler)
        if not accepted:
            return
        result = host._force_reset_solver_scope(
            payload.get("scope"), payload.get("challenge_id")
        )
        status = 200 if result.get("ok") or result.get("stale_challenge") else 409
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_CHALLENGE_FORCE_RESET_REJECTED",
                message="验证码尚未达到保底重置时间或状态不匹配",
                details=result,
            )
            return
        handler.send_json(result)

    def _post_auth_complete(handler: AuthCommandHandler) -> None:
        if not host._require_node_auth(handler):
            return
        accepted, payload = host._read_json_body(handler)
        if not accepted:
            return
        if (
            payload.get("cdp_endpoint")
            and not host._cdp_endpoint_permitted(payload["cdp_endpoint"])
        ) or (
            payload.get("cookie_snapshot_path")
            and not host._resolve_auth_cookie_snapshot_path(payload)
        ):
            handler.send_error_json(
                status=400,
                code="COLLECTION_AUTH_TARGET_REJECTED",
                message="Untrusted authentication target",
                details={},
            )
            return
        try:
            result = host._collection_observer_auth_complete_payload(payload)
        except Exception as e:  # noqa: BLE001 - preserve HTTP error boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_AUTH_COMPLETE_FAILED",
                message="人工认证完成通知失败",
                details={"error": str(e)},
            )
            return
        status = 200 if result.get("ok") or result.get("stale_challenge") else 400
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_OBSERVER_AUTH_COMPLETE_REJECTED",
                message="人工认证完成通知被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    def _post_auth_resume_after_cooldown(handler: AuthCommandHandler) -> None:
        if not host._require_node_auth(handler):
            return
        accepted, payload = host._read_json_body(handler)
        if not accepted:
            return
        try:
            result = host._collection_observer_resume_after_cooldown_payload(payload)
        except Exception as e:  # noqa: BLE001 - preserve HTTP error boundary
            handler.send_error_json(
                status=500,
                code="COLLECTION_OBSERVER_AUTH_RESUME_FAILED",
                message="冷却后恢复采集失败",
                details={"error": str(e)},
            )
            return
        status = 200 if result.get("ok") or result.get("stale_challenge") else 400
        if status != 200:
            handler.send_error_json(
                status=status,
                code="COLLECTION_OBSERVER_AUTH_RESUME_REJECTED",
                message="冷却后恢复采集请求被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    return AuthCommandHandlers(
        _post_auth_force_reset, _post_auth_complete, _post_auth_resume_after_cooldown
    )
