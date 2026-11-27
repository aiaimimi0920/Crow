"""Regression coverage for Slice 6 module splits and PostgreSQL backup status."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def test_split_mixins_preserve_method_resolution(tmp_path) -> None:
    from src import server_hybrid_escalation_events, server_hybrid_events
    from src.captcha_orchestration import CaptchaOrchestrationMixin
    from src.captcha_orchestration_preflight import CaptchaOrchestrationPreflightMixin
    from src.captcha_os_drag_profiles import CaptchaOSDragProfilesMixin
    from src.captcha_os_input import CaptchaOSInputMixin
    from src.collection.detail_service import DetailCollectionService
    from src.collection.detail_service_maintenance import (
        DetailServiceMaintenanceMixin,
    )

    assert issubclass(CaptchaOSInputMixin, CaptchaOSDragProfilesMixin)
    assert hasattr(CaptchaOSInputMixin, "_os_drag_profile")
    assert hasattr(CaptchaOSInputMixin, "_do_drag_os_target")

    assert issubclass(CaptchaOrchestrationMixin, CaptchaOrchestrationPreflightMixin)
    assert hasattr(CaptchaOrchestrationMixin, "_run_solve_preflight_and_fallbacks")
    assert hasattr(CaptchaOrchestrationMixin, "solve")

    assert issubclass(DetailCollectionService, DetailServiceMaintenanceMixin)
    assert hasattr(DetailCollectionService, "run_maintenance")
    assert hasattr(DetailCollectionService, "backfill_archived")

    assert (
        server_hybrid_events._hybrid_collection_operator_escalation_event_summary
        is server_hybrid_escalation_events._hybrid_collection_operator_escalation_event_summary
    )
    summary = server_hybrid_events._hybrid_collection_operator_escalation_event_summary(
        tmp_path
    )
    assert summary["available"] is False


def test_postgres_backup_status_surfaces_in_lightweight_and_full_status(
    tmp_path,
) -> None:
    from src.collection_status_payload import (
        build_lightweight_status,
        load_postgres_backup_status,
    )

    assert load_postgres_backup_status(tmp_path) is None

    generated = (
        (datetime.now(timezone.utc) - timedelta(hours=2))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    status_path = tmp_path / "postgres-backup-status.json"
    status_path.write_text(
        json.dumps(
            {
                "ok": True,
                "generated_at": generated,
                "latest_backup_file": "fapaifang-20261127-040000.dump",
                "size_bytes": 1048576,
                "toc_entries": 42,
                "retained_backups": 5,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_postgres_backup_status(tmp_path)
    assert loaded is not None
    assert loaded["ok"] is True
    assert loaded["latest_backup_file"] == "fapaifang-20261127-040000.dump"
    assert 1.9 <= float(loaded["age_hours"]) <= 2.2

    lightweight = build_lightweight_status(
        {"counts": {}, "metadata": {"valid": True}},
        load_api_metrics=dict,
        empty_counts=dict,
        load_runtime_snapshot=lambda: {
            "paused": False,
            "captcha_solver": {},
            "auth_recovery": {},
            "collection_scopes": {},
        },
        load_build_info=lambda: {"version": "test"},
        database_enabled=lambda: True,
        runtime_state_label=lambda _: "运行中",
        load_data_root=lambda: tmp_path,
    )
    assert lightweight["postgres_backup"]["ok"] is True

    status_path.write_text("{corrupt", encoding="utf-8")
    corrupt = load_postgres_backup_status(tmp_path)
    assert corrupt == {"ok": False, "reason": "invalid_backup_status_json"}


def test_health_receipt_identifies_one_owned_dump_and_requires_fresh_timestamp(
    tmp_path,
):
    from src.postgres_backup_status import read_receipt

    marker = tmp_path / "postgres-backup-status.json"
    archives = tmp_path / "scheduled"
    archives.mkdir()
    name = "fapaifang-20261127-040000.dump"
    (archives / name).write_bytes(bytes(1024))
    assert read_receipt(tmp_path, archive_dir=archives) is None
    row = dict(ok=True, latest_backup_file=name, size_bytes=1024, toc_entries=5)

    def observe(hours, **changes):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        marker.write_text(
            json.dumps({**row, "generated_at": stamp, **changes}), encoding="utf-8"
        )
        return read_receipt(tmp_path, archive_dir=archives)

    assert observe(2)["ok"]
    for hours, reason in [(24, "stale_backup"), (-1, "future_backup_timestamp")]:
        assert observe(hours)["reason"] == reason
    assert not observe(1, ok="false")["ok"]
    assert not observe(1, latest_backup_file="../" + name)["ok"]
    assert observe(1, size_bytes=2048)["reason"] == "backup_file_mismatch"
    assert observe(1, generated_at="bad")["reason"] == "invalid_backup_timestamp"
