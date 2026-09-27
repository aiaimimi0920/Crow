"""Pipeline and maintenance admission with explicit facade dependencies."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol, cast


class PipelineHandler(Protocol):
    def send_error_json(
        self, *, status: int, code: str, message: str, details: dict[str, object]
    ) -> None: ...
    def _submit_pipeline_job(self, config: object, error_code: str) -> object: ...
    def _submit_maintenance_job(self, kind: str, error_code: str) -> object: ...


class PipelineHost(Protocol):
    AVM_SERVICE: object
    DATA_DIR: str | Path

    def AVMPipelineConfig(self, **options: object) -> object: ...
    def _require_control_plane(self, handler: PipelineHandler) -> bool: ...
    def _read_json_body(
        self, handler: PipelineHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _resolve_pipeline_data_dir(self, requested: object) -> str | None: ...


@dataclass(frozen=True)
class PipelineSubmissionHandlers:
    _resolve_pipeline_data_dir: Callable[[object], str | None]
    _post_analysis_run: Callable[[PipelineHandler], None]
    _post_detail_maintenance: Callable[[PipelineHandler], None]
    _post_fetch_missing_detail_archives: Callable[[PipelineHandler], None]
    _post_archive_detail_replay: Callable[[PipelineHandler], None]
    _post_start_all_subtasks: Callable[[PipelineHandler], None]
    _post_run_all_subtasks_sync: Callable[[PipelineHandler], None]
    __all__: ClassVar[list[str]] = [
        "_resolve_pipeline_data_dir",
        "_post_analysis_run",
        "_post_detail_maintenance",
        "_post_fetch_missing_detail_archives",
        "_post_archive_detail_replay",
        "_post_start_all_subtasks",
        "_post_run_all_subtasks_sync",
    ]


def bind_pipeline_submissions(host: PipelineHost) -> PipelineSubmissionHandlers:
    def _resolve_pipeline_data_dir(requested: object) -> str | None:
        """Only the configured root or its descendants may drive the pipeline."""
        active_root = Path(
            getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR)
        ).resolve()
        if requested in (None, ""):
            return str(active_root)
        try:
            candidate = Path(str(requested)).resolve()
            candidate.relative_to(active_root)
        except (OSError, ValueError, TypeError):
            return None
        return str(candidate)

    def _post_analysis_run(self: PipelineHandler) -> None:
        if not host._require_control_plane(self):
            return
        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        invalid_fields = []
        try:
            alerts_threshold = float(
                cast(str | int | float, payload.get("alerts_threshold", 0.15))
            )
        except (TypeError, ValueError):
            alerts_threshold = None
            invalid_fields.append("alerts_threshold")
        try:
            alerts_limit = int(
                cast(str | int | float, payload.get("alerts_limit", 500))
            )
        except (TypeError, ValueError):
            alerts_limit = None
            invalid_fields.append("alerts_limit")
        data_dir = host._resolve_pipeline_data_dir(payload.get("data_dir"))
        if data_dir is None:
            invalid_fields.append("data_dir")
        if invalid_fields:
            self.send_error_json(
                status=400,
                code="AVM_INVALID_PIPELINE_CONFIG",
                message="pipeline 配置参数无效",
                details={"invalid_fields": invalid_fields},
            )
            return
        config = host.AVMPipelineConfig(
            data_dir=data_dir,
            alerts_threshold=alerts_threshold,
            alerts_limit=alerts_limit,
        )
        self._submit_pipeline_job(config, "AVM_PIPELINE_RUN_FAILED")

    def _post_detail_maintenance(self: PipelineHandler) -> None:
        self._submit_maintenance_job(
            "recent_enrich_maintenance", "AVM_RECENT_ENRICH_MAINTENANCE_FAILED"
        )

    def _post_fetch_missing_detail_archives(self: PipelineHandler) -> None:
        self._submit_maintenance_job(
            "fetch_missing_detail_archives", "AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED"
        )

    def _post_archive_detail_replay(self: PipelineHandler) -> None:
        self._submit_maintenance_job(
            "archive_detail_replay", "AVM_ARCHIVE_DETAIL_REPLAY_FAILED"
        )

    def _post_start_all_subtasks(self: PipelineHandler) -> None:
        if not host._require_control_plane(self):
            return
        accepted, _payload = host._read_json_body(self)
        if not accepted:
            return
        self._submit_pipeline_job(
            host.AVMPipelineConfig(data_dir=host._resolve_pipeline_data_dir(None)),
            "AVM_START_ALL_SUBTASKS_FAILED",
        )

    def _post_run_all_subtasks_sync(self: PipelineHandler) -> None:
        if not host._require_control_plane(self):
            return
        accepted, _payload = host._read_json_body(self)
        if not accepted:
            return
        self._submit_pipeline_job(
            host.AVMPipelineConfig(data_dir=host._resolve_pipeline_data_dir(None)),
            "AVM_RUN_ALL_SUBTASKS_SYNC_FAILED",
        )

    return PipelineSubmissionHandlers(
        _resolve_pipeline_data_dir,
        _post_analysis_run,
        _post_detail_maintenance,
        _post_fetch_missing_detail_archives,
        _post_archive_detail_replay,
        _post_start_all_subtasks,
        _post_run_all_subtasks_sync,
    )
