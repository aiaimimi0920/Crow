from __future__ import annotations

import json
import logging
from src.project_environment import getenv as project_getenv
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, BinaryIO, ClassVar
from urllib.parse import urlparse
from urllib.request import Request

if TYPE_CHECKING:
    from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SolverDispatch:
    runtime: Callable[[], RuntimeState]
    clock: Callable[[], float]
    monotonic: Callable[[], float]
    event: Callable[[], Event]
    open_url: Callable[..., AbstractContextManager[BinaryIO]]
    runner: Callable[[], Callable[..., object]]
    submit: Callable[..., object]
    normalize_scope: Callable[[object], str | None]
    scope_flag_path: Callable[[str], str]
    flag_path: Callable[[], str]
    infer_scope: Callable[[dict[str, str]], str | None]
    scope_status: Callable[[str], Mapping[str, object]]
    flag_scope: Callable[[], str | None]
    flag_manual_only: Callable[[], bool]
    env_flag: Callable[[str, bool], bool]
    ready_timeout: Callable[[], int]
    probe_timeout: Callable[[], float]
    background_url: Callable[[str], str]
    sample_urls: Callable[[dict[str, object]], Sequence[str]]
    status: Callable[[], object]
    last_scope: Callable[[], str]
    seed_pending: Callable[[object], bool]
    build_request: Callable[[object], dict[str, object]]
    default_request: Callable[[], dict[str, object]]
    request_scope: Callable[[object], str]
    prefer_seed_payload: Callable[[object], bool]
    seed_priority_request: Callable[[object], dict[str, object]]
    prefer_seed_retry: Callable[[], bool]
    flag_request: Callable[[], dict[str, object]]
    retry_enabled: Callable[[str | None], bool]
    retry_interval: Callable[[], int]
    remote_endpoint: Callable[[str], bool]
    reserve: Callable[[], object | None]
    release: Callable[[object | None], None]

    __all__: ClassVar[list[str]] = [
        "_write_solver_manual_required_flag",
        "_solver_manual_flag_scope",
        "_solver_manual_flag_is_manual_only",
        "_manual_solver_retry_enabled",
        "_manual_solver_retry_interval_seconds",
        "_solver_max_runtime_seconds",
        "_solver_worker_quiesce_seconds",
        "_solver_cdp_ready_timeout_seconds",
        "_wait_for_solver_cdp_ready",
        "_solver_cdp_probe_timeout_seconds",
        "_probe_solver_cdp_endpoint",
        "_manual_solver_retry_poll_seconds",
        "_captcha_solver_background_url",
        "_solver_manual_flag_request",
        "_default_manual_solver_retry_request",
        "_prefer_seed_manual_solver_retry_request",
        "_seed_priority_manual_solver_retry_request",
        "_prefer_seed_solver_request_for_payload",
        "_seed_priority_solver_request",
        "_manual_solver_retry_request",
        "_manual_solver_retry_next_epoch",
        "_solver_submission_pending",
        "_reserve_solver_submission",
        "_release_solver_submission",
        "_activate_solver_submission",
        "_solver_cdp_endpoint_is_remote",
        "_solver_request_delegated_to_node",
        "_submit_solver_request",
    ]

    def _write_solver_manual_required_flag(
        self, created_at_epoch: float, *, scope: str | None = None
    ) -> str | None:
        from src.solver_manual_pause import write_manual_flag

        normalized_scope = self.normalize_scope(scope) or None
        return write_manual_flag(
            created_at_epoch,
            runtime=self.runtime(),
            path=self.scope_flag_path(normalized_scope)
            if normalized_scope
            else self.flag_path(),
            scope=normalized_scope,
        )

    def _solver_manual_flag_scope(self) -> str | None:
        from src.solver_manual_retry import manual_flag_scope

        return manual_flag_scope(self.flag_path, self.normalize_scope)

    def _solver_manual_flag_is_manual_only(self) -> bool:
        from src.solver_manual_retry import manual_flag_is_manual_only

        return manual_flag_is_manual_only(self.flag_path)

    def _manual_solver_retry_enabled(self, scope: str | None = None) -> bool:
        from src.solver_manual_retry import manual_retry_enabled

        return manual_retry_enabled(
            runtime=self.runtime(),
            scope=self.normalize_scope(scope),
            infer_scope=self.infer_scope,
            scope_status=self.scope_status,
            flag_scope=self.flag_scope,
            flag_manual_only=self.flag_manual_only,
            configured_enabled=lambda: self.env_flag(
                "FAPAI_SOLVER_MANUAL_RETRY_ENABLED", True
            ),
        )

    def _manual_solver_retry_interval_seconds(self) -> int:
        raw = project_getenv("CROW_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "180")
        try:
            value = int(str(raw or "").strip())
        except ValueError:
            value = 180
        if value < 0:
            return 180
        return value

    def _solver_max_runtime_seconds(self) -> int:
        raw = project_getenv("CROW_SOLVER_MAX_RUNTIME_SECONDS", "180")
        try:
            value = int(str(raw or "").strip())
        except ValueError:
            value = 180
        if value <= 0:
            return 180
        return value

    def _solver_worker_quiesce_seconds(self) -> int:
        raw = project_getenv("CROW_SOLVER_WORKER_QUIESCE_SECONDS", "0")
        try:
            value = int(str(raw or "").strip())
        except ValueError:
            value = 0
        return max(0, min(value, 300))

    def _solver_cdp_ready_timeout_seconds(self) -> int:
        raw = project_getenv("CROW_SOLVER_CDP_READY_TIMEOUT_SECONDS", "0")
        try:
            value = int(str(raw or "").strip())
        except ValueError:
            value = 0
        return max(0, min(value, 600))

    def _wait_for_solver_cdp_ready(
        self,
        solver_request: dict[str, object] | None,
        *,
        deadline: float | None = None,
        cancel_checker: Callable[[], bool] | None = None,
    ) -> bool:
        timeout_seconds = self.ready_timeout()
        request_payload = solver_request if isinstance(solver_request, dict) else {}
        cdp_endpoint = (
            str(request_payload.get("cdp_endpoint") or "").strip().rstrip("/")
        )
        if timeout_seconds <= 0 or not cdp_endpoint:
            return True

        logger.info(
            f"[SOLVER] Waiting up to {timeout_seconds}s for a stable CDP target list at "
            f"{cdp_endpoint}."
        )
        deadline = (
            min(deadline, self.monotonic() + timeout_seconds)
            if deadline is not None
            else self.monotonic() + timeout_seconds
        )
        consecutive_healthy_probes = 0
        while self.monotonic() < deadline:
            if cancel_checker is not None and cancel_checker():
                return False
            try:
                request = Request(
                    f"{cdp_endpoint}/json/list", headers={"Accept": "application/json"}
                )
                with self.open_url(
                    request, timeout=max(0.001, min(3, deadline - self.monotonic()))
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                healthy = isinstance(payload, list)
            except Exception:  # noqa: BLE001 - a failed CDP probe resets readiness
                healthy = False

            if healthy:
                consecutive_healthy_probes += 1
                if consecutive_healthy_probes >= 2 and self.monotonic() < deadline:
                    logger.info(
                        "[SOLVER] CDP target list is stable; starting solver control."
                    )
                    return True
            else:
                consecutive_healthy_probes = 0
            wake = self.event()
            retry_at = min(deadline, self.monotonic() + 2)
            while self.monotonic() < retry_at:
                if cancel_checker is not None and cancel_checker():
                    return False
                wake.wait(min(0.1, max(0, retry_at - self.monotonic())))

        logger.warning(
            "[SOLVER] CDP did not become stable within %ss.", timeout_seconds
        )
        return False

    def _solver_cdp_probe_timeout_seconds(self) -> float:
        raw = project_getenv("CROW_SOLVER_CDP_PROBE_TIMEOUT_SECONDS", "3")
        try:
            value = float(str(raw or "").strip())
        except ValueError:
            value = 3.0
        return max(0.5, min(value, 30.0))

    def _probe_solver_cdp_endpoint(self, cdp_endpoint: str) -> bool:
        """轻量探测 CDP 是否可达；没有 endpoint 时视为通过。

        manual retry 会先走这里，避免浏览器已经掉线时还不停地清 pause、重投
        solver，最后把 manual_retry_attempts 刷到几千次。
        """
        endpoint = str(cdp_endpoint or "").strip().rstrip("/")
        if not endpoint:
            return True
        try:
            request = Request(
                f"{endpoint}/json/version", headers={"Accept": "application/json"}
            )
            with self.open_url(request, timeout=self.probe_timeout()) as response:
                json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - failed probes are reported as unhealthy
            return False
        return True

    def _manual_solver_retry_poll_seconds(self) -> int:
        raw = project_getenv("CROW_SOLVER_MANUAL_RETRY_POLL_SECONDS", "30")
        try:
            value = int(str(raw or "").strip())
        except ValueError:
            value = 30
        return max(value, 1)

    def _captcha_solver_background_url(self, url: str) -> str:
        target_url = str(url or "").strip()
        if not target_url:
            return ""
        if "__captcha_solver_bg=1" in target_url:
            return target_url
        separator = "&" if "?" in target_url else "?"
        return f"{target_url}{separator}__captcha_solver_bg=1"

    def _solver_manual_flag_request(self) -> dict[str, object]:
        from src.solver_manual_retry import manual_flag_request

        return manual_flag_request(self.flag_path())

    def _default_manual_solver_retry_request(self) -> dict[str, object]:
        default_url = self.background_url(self.sample_urls({})[0])
        return {"target_url": default_url} if default_url else {}

    def _prefer_seed_manual_solver_retry_request(self) -> bool:
        try:
            status_payload = self.status()
        except Exception:  # noqa: BLE001 - unavailable status must not reroute work
            return False
        return self.last_scope() == "detail" and self.seed_pending(status_payload)

    def _seed_priority_manual_solver_retry_request(
        self,
        current_request: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request = dict(current_request or {})
        default_request = self.build_request(self.default_request())
        if default_request.get("target_url"):
            request["target_url"] = default_request["target_url"]
        return request

    def _prefer_seed_solver_request_for_payload(
        self,
        request_payload: dict[str, object] | None = None,
        *,
        status_payload: object = None,
    ) -> bool:
        if self.request_scope(request_payload) != "detail":
            return False
        if status_payload is None:
            try:
                status_payload = self.status()
            except Exception:  # noqa: BLE001 - unavailable status must not reroute work
                return False
        if not isinstance(status_payload, dict):
            return False
        return self.seed_pending(status_payload)

    def _seed_priority_solver_request(
        self,
        request_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        solver_request = self.build_request(request_payload or {})
        if not solver_request.get("target_url"):
            return solver_request
        if self.prefer_seed_payload(solver_request):
            solver_request["challenge_target_url"] = solver_request["target_url"]
            return self.seed_priority_request(solver_request)
        return solver_request

    def _manual_solver_retry_request(self) -> dict[str, object]:
        solver_request = self.build_request(
            self.runtime().recovery.snapshot().last_request
            if isinstance(self.runtime().recovery.snapshot().last_request, dict)
            else {}
        )
        if solver_request.get("target_url"):
            if self.prefer_seed_retry():
                return self.seed_priority_request(solver_request)
            return solver_request
        solver_request = self.build_request(self.flag_request())
        if solver_request.get("target_url"):
            return solver_request
        return self.build_request(self.default_request())

    def _manual_solver_retry_next_epoch(self, now: float | None = None) -> float | None:
        with self.runtime().lock:
            recovery = self.runtime().recovery.snapshot()
            execution = self.runtime().solver.snapshot()
        retry_scope = self.infer_scope(recovery.last_request)
        if not self.retry_enabled(retry_scope or None):
            return None
        interval = self.retry_interval()
        current_time = self.clock() if now is None else now
        base_epoch = max(
            recovery.required_epoch,
            recovery.retry_last_epoch,
            execution.finished_at,
        )
        if base_epoch <= 0:
            return current_time
        return base_epoch + interval

    def _solver_submission_pending(self) -> bool:
        return self.runtime().solver.snapshot().pending_token is not None

    def _reserve_solver_submission(self) -> object | None:
        return self.runtime().solver.reserve()

    def _release_solver_submission(self, token: object | None) -> None:
        self.runtime().solver.release(token)

    def _activate_solver_submission(
        self,
        solver_request: dict[str, str] | None,
        token: object | None,
    ) -> tuple[bool, str, float]:
        with self.runtime().lock:
            recovery = self.runtime().recovery.snapshot()
            result = self.runtime().solver.activate(
                self.clock(),
                token=token,
                resume_epoch=recovery.resume_epoch,
                cancel_epoch=recovery.cancel_epoch,
            )
            if result[0]:
                self.runtime().recovery.set_request(
                    dict(solver_request) if isinstance(solver_request, dict) else {}
                )
            return result

    def _solver_cdp_endpoint_is_remote(self, cdp_endpoint: str) -> bool:
        """Check if the CDP endpoint belongs to a remote node (not the local machine).

        Returns True when the endpoint hostname is not a loopback address, indicating
        the solver runs on a different host than the CDP browser. In that case the
        local solver cannot use OS-level mouse drag and must defer to the node's
        own solver process.
        """
        endpoint = str(cdp_endpoint or "").strip().rstrip("/")
        if not endpoint:
            return False
        try:
            parsed = urlparse(endpoint)
        except ValueError:
            return False
        hostname = str(parsed.hostname or "").lower()
        if not hostname:
            return False
        # Local loopback addresses are on the same machine.
        if hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
            return False
        # host.docker.internal resolves to the Docker host — same machine when
        # the solver runs inside a container on the host.
        return hostname not in {"host.docker.internal", "192.168.65.254"}

    def _solver_request_delegated_to_node(
        self, solver_request: dict[str, object] | None
    ) -> bool:
        request = solver_request if isinstance(solver_request, dict) else {}
        node_id = str(request.get("node_id") or "").strip().lower()
        if node_id == "pc2":
            return True
        return self.remote_endpoint(str(request.get("cdp_endpoint") or ""))

    def _submit_solver_request(self, solver_request: dict[str, object]) -> bool:
        token = self.reserve()
        if token is None:
            return False

        run_solver = self.runner()
        try:
            self.submit(run_solver, solver_request, token)
        except Exception:
            self.release(token)
            raise
        return True
