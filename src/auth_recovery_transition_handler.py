"""Authenticated cross-device recovery transition HTTP boundary."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast
from urllib.parse import urlparse


class RecoveryCoordinator(Protocol):
    def register_stage_auth_pc2(self) -> object: ...
    def claim(self, role: str, recovery_id: str, node_id: str) -> dict[str, object]: ...
    def snapshot_ready(
        self,
        recovery_id: str,
        *,
        sha256: str,
        cookie_count: int,
        created_at_epoch: float,
    ) -> dict[str, object]: ...
    def pc2_restarting(self, recovery_id: str) -> dict[str, object]: ...


class RecoveryClock(Protocol):
    def time(self) -> float: ...


class RecoveryTransitionHandler(Protocol):
    path: str
    headers: Mapping[str, str]

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self,
        *,
        status: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None: ...


class RecoveryTransitionHost(Protocol):
    NAS_AUTH_RECOVERY: RecoveryCoordinator
    time: RecoveryClock

    def _nas_auth_recovery_authorized(
        self, headers: Mapping[str, str]
    ) -> tuple[bool, object]: ...
    def _read_json_body(
        self, handler: RecoveryTransitionHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _nas_auth_recovery_result(
        self, payload: dict[str, object]
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class RecoveryTransitionHandlers:
    _post_auth_recovery_transition: Callable[[RecoveryTransitionHandler], None]
    __all__: ClassVar[list[str]] = ["_post_auth_recovery_transition"]


def bind_recovery_transitions(
    host: RecoveryTransitionHost,
) -> RecoveryTransitionHandlers:
    def _post_auth_recovery_transition(handler: RecoveryTransitionHandler) -> None:
        authorized, auth_error = host._nas_auth_recovery_authorized(handler.headers)
        if not authorized:
            handler.send_error_json(
                status=403,
                code="COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                message="跨设备认证恢复凭据无效",
                details={"error": auth_error},
            )
            return
        accepted, payload = host._read_json_body(handler)
        if not accepted:
            return
        if urlparse(handler.path).path.endswith("/heartbeat"):
            if payload.get("protocol_version") != 2 or payload.get("node_id") != "pc2":
                handler.send_error_json(
                    status=400,
                    code="COLLECTION_AUTH_RECOVERY_REJECTED",
                    message="PC2 protocol version 2 is required",
                )
                return
            host.NAS_AUTH_RECOVERY.register_stage_auth_pc2()
            handler.send_json({"ok": True})
            return
        recovery_id = str(payload.get("recovery_id") or "").strip()
        if not recovery_id:
            result: dict[str, object] = {
                "ok": False,
                "error": "recovery_id is required",
            }
        elif urlparse(handler.path).path.endswith("/claim"):
            role = str(payload.get("role") or "").strip().lower()
            node_id = str(payload.get("node_id") or "").strip().lower()
            if (role, node_id) not in {("pc1", "pc1"), ("pc2", "pc2")}:
                result = {
                    "ok": False,
                    "error": "role and node_id must identify pc1 or pc2",
                }
            else:
                result = host.NAS_AUTH_RECOVERY.claim(role, recovery_id, node_id)
        elif urlparse(handler.path).path.endswith("/snapshot_ready"):
            try:
                result = host.NAS_AUTH_RECOVERY.snapshot_ready(
                    recovery_id,
                    sha256=str(payload.get("sha256") or ""),
                    cookie_count=int(cast(int, payload.get("cookie_count") or 0)),
                    created_at_epoch=float(
                        cast(float, payload.get("created_at_epoch") or host.time.time())
                    ),
                )
            except (TypeError, ValueError) as error:
                result = {"ok": False, "error": str(error)}
        elif urlparse(handler.path).path.endswith("/pc2_restarting"):
            result = host.NAS_AUTH_RECOVERY.pc2_restarting(recovery_id)
        else:
            result = host._nas_auth_recovery_result(payload)
        if not result.get("ok"):
            handler.send_error_json(
                status=409 if result.get("stale_recovery") else 400,
                code="COLLECTION_AUTH_RECOVERY_REJECTED",
                message="跨设备认证恢复请求被拒绝",
                details=result,
            )
            return
        handler.send_json(result)

    return RecoveryTransitionHandlers(_post_auth_recovery_transition)
