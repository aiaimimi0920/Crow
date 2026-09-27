"""Asynchronous compatibility report admission with request-scoped dependencies."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol, cast


class ReportHandler(Protocol):
    def _enqueue_collection_job(
        self, kind: str, run: Callable[[], object], error_code: str
    ) -> None: ...


class ReportHost(Protocol):
    AVM_SERVICE: object
    DATA_DIR: str | Path

    def _read_json_body(
        self, handler: ReportHandler
    ) -> tuple[bool, dict[str, object]]: ...
    def _avm_operator_eval_summary(
        self, root: Path, *, gate_report_override: dict[str, object]
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class ReportJobHandlers:
    _post_drift_report: Callable[[ReportHandler], None]
    _post_release_gate: Callable[[ReportHandler], None]
    _post_recent_gap_audit: Callable[[ReportHandler], None]
    __all__: ClassVar[list[str]] = [
        "_post_drift_report",
        "_post_release_gate",
        "_post_recent_gap_audit",
    ]


def bind_report_jobs(host: ReportHost) -> ReportJobHandlers:
    def _post_drift_report(self: ReportHandler) -> None:
        from tools.check_feature_drift import generate_drift_report

        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        try:
            window_days = int(cast(str | int | float, payload.get("window_days", 30)))
        except (TypeError, ValueError):
            window_days = 30
        if window_days < 0:
            window_days = 30
        root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
        avm_dir = root / "avm"

        def run() -> object:
            return generate_drift_report(
                archive_dir=root / "archive",
                output_path=avm_dir / "drift_alerts.json",
                window_days=window_days,
            )

        self._enqueue_collection_job("drift_report", run, "AVM_DRIFT_FAILED")

    def _post_release_gate(self: ReportHandler) -> None:
        from tools.avm_release_gate import generate_release_gate_report

        from .collection_jobs import CollectionJobFailure

        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        try:
            window_days = int(cast(str | int | float, payload.get("window_days", 7)))
        except (TypeError, ValueError):
            window_days = 7
        if window_days < 0:
            window_days = 7
        try:
            min_sample_size = int(
                cast(str | int | float, payload.get("min_sample_size", 1000))
            )
        except (TypeError, ValueError):
            min_sample_size = 1000
        if min_sample_size < 0:
            min_sample_size = 1000
        try:
            smoke_sample_size = int(
                cast(str | int | float, payload.get("smoke_sample_size", 0))
            )
        except (TypeError, ValueError):
            smoke_sample_size = 0
        if smoke_sample_size < 0:  # noqa: PLR1730 - keep route validation explicit
            smoke_sample_size = 0
        root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
        avm_dir = root / "avm"
        summarize = host._avm_operator_eval_summary

        def run() -> object:
            output = generate_release_gate_report(
                data_root=root,
                eval_report_path=avm_dir / "eval_report.json",
                gate_report_path=avm_dir / "release_gate.json",
                window_days=window_days,
                min_sample_size=min_sample_size,
                smoke_sample_size=smoke_sample_size,
            )
            if isinstance(output, dict):
                try:
                    output = {**output, **summarize(root, gate_report_override=output)}
                except Exception as error:
                    raise CollectionJobFailure(
                        "AVM_RELEASE_GATE_SUMMARY_FAILED"
                    ) from error
            return output

        self._enqueue_collection_job(
            "release_gate_report", run, "AVM_RELEASE_GATE_FAILED"
        )

    def _post_recent_gap_audit(self: ReportHandler) -> None:
        from tools.audit_recent_avm_gaps import build_recent_gap_audit

        from .archive_json_io import write_json

        accepted, payload = host._read_json_body(self)
        if not accepted:
            return
        try:
            window_days = int(cast(str | int | float, payload.get("window_days", 7)))
        except (TypeError, ValueError):
            window_days = 7
        if window_days < 0:
            window_days = 7
        try:
            sample_limit = int(cast(str | int | float, payload.get("sample_limit", 20)))
        except (TypeError, ValueError):
            sample_limit = 20
        if sample_limit < 0:
            sample_limit = 20
        root = Path(getattr(host.AVM_SERVICE, "data_dir", host.DATA_DIR))
        avm_dir = root / "avm"

        def run() -> object:
            output = build_recent_gap_audit(
                data_root=root, window_days=window_days, sample_limit=sample_limit
            )
            avm_dir.mkdir(parents=True, exist_ok=True)
            write_json(avm_dir / "recent_gap_audit.json", output, indent=2)
            return output

        self._enqueue_collection_job(
            "recent_gap_audit", run, "AVM_RECENT_GAP_AUDIT_FAILED"
        )

    return ReportJobHandlers(
        _post_drift_report, _post_release_gate, _post_recent_gap_audit
    )
