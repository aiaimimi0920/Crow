from pathlib import Path

DISPATCH_SOURCE = Path(__file__).parents[2].joinpath("src", "server_solver_dispatch.py")
ANALYSIS_SOURCE = (
    Path(__file__).parents[2].joinpath("src", "server_handler_analysis.py")
)
AUTH_RECOVERY_SOURCE = (
    Path(__file__).parents[2].joinpath("src", "server_auth_recovery.py")
)
AUTO_TUNING_SOURCE = Path(__file__).parents[2].joinpath("src", "server_auto_tuning.py")
COLLECTION_STATUS_SOURCE = (
    Path(__file__).parents[2].joinpath("src", "collection_repository_status.py")
)


def test_solver_preflight_failure_uses_logging_without_printing_exception(
    monkeypatch, caplog, capsys
) -> None:
    from types import SimpleNamespace

    from src import server
    from src.runtime_state import RuntimeState

    released = []
    state = RuntimeState()
    token = object()
    monkeypatch.setattr(server, "RUNTIME", state)
    monkeypatch.setattr(server, "_challenge_scope_for_request", lambda request: "")
    monkeypatch.setattr(
        server, "_captcha_solver_runtime_status", lambda: {"manual_required": True}
    )

    def preflight():
        raise RuntimeError("preflight unavailable")

    monkeypatch.setattr(
        server,
        "_build_solver_for_request",
        lambda request: SimpleNamespace(_preflight_current_challenge=preflight),
    )
    monkeypatch.setattr(server, "_release_solver_submission", released.append)
    object.__new__(server.DataHandler).run_solver(submission_token=token)
    records = [
        record
        for record in caplog.records
        if "Stale auth-lock preflight failed" in record.getMessage()
    ]
    assert len(records) == 1 and records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], RuntimeError)
    assert released == [token]
    assert state.solver.current is None
    assert capsys.readouterr().out == ""


def test_solver_cdp_readiness_uses_structured_logging() -> None:
    source = DISPATCH_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert "logger.info(" in source
    assert "logger.warning(" in source
    assert "Waiting up to {timeout_seconds}s for a stable CDP target list" in source
    assert "print(" not in source
    assert (
        'print("[SOLVER] CDP target list is stable; starting solver control.")'
        not in source
    )
    assert (
        'print(f"[SOLVER] CDP did not become stable within {timeout_seconds}s.")'
        not in source
    )


def test_avm_evaluate_failure_uses_exception_logging() -> None:
    source = ANALYSIS_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert "logger.exception('[AVM] Evaluate failed')" in source
    assert "print(f'[AVM] Evaluate failed: {e}')" not in source


def test_auth_recovery_watchdog_uses_structured_logging() -> None:
    source = AUTH_RECOVERY_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert "logger.warning(" in source
    assert 'logger.exception("[AUTH-RECOVERY] Watchdog sample failed")' in source
    assert "print(" not in source


def test_auto_tuner_uses_structured_logging() -> None:
    source = AUTO_TUNING_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.info("[AUTO-TUNER] Started (5-minute intervals)")' in source
    assert 'logger.exception("[AUTO-TUNER] Error")' in source
    assert "print(" not in source


def test_collection_status_db_query_uses_structured_logging() -> None:
    source = COLLECTION_STATUS_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.exception("[DB] Pending task query failed")' in source
    assert "print(" not in source
