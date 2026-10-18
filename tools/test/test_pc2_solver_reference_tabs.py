import logging

from tools import pc2_solver_reference_tabs as tabs
from tools.pc2_solver_diagnostics import solver_attempt_diagnostics


def test_execution_reports_completed_failed_drags(monkeypatch):
    from tools import pc2_solver_execution as execution

    calls = []
    monkeypatch.setattr(
        execution, "record_failed_drags", lambda *args: calls.append(args)
    )
    monkeypatch.setattr("tools.pc2_solver_diagnostics.log_event", lambda _: None)

    def solve(*args, **kwargs):
        logger = logging.getLogger("src.captcha_slider")
        logger.info("[SOLVER] Drag complete. Verifying...")
        logger.info(
            "[SOLVER] Verification: success=False, sliderGone=False, challengeGone=False, hasError=True"
        )
        return False

    monkeypatch.setattr(execution, "run_solver_local", solve)
    assert (
        execution.run_solver_local_with_deadline("offline", "target", timeout_seconds=0)
        is False
    )
    assert calls == [("offline", 1)]


def test_counts_only_verification_after_completed_drag(monkeypatch):
    monkeypatch.setattr("tools.pc2_solver_diagnostics.log_event", lambda _: None)
    logger = logging.getLogger("src.captcha_slider")
    failed = "[SOLVER] Verification: success=False, sliderGone=False, challengeGone=False, hasError=True"
    with solver_attempt_diagnostics() as stats:
        logger.info(failed)
        logger.info("[SOLVER] Drag complete. Verifying...")
        logger.info(failed)
        logger.info(failed)
        logger.info("[SOLVER] Drag complete. Verifying...")
        logger.info(failed.replace("success=False", "success=True"))
    assert stats.failed_drag_verifications == 1


def test_threshold_persistence_presence_and_new_challenge(tmp_path, monkeypatch):
    monkeypatch.setattr(tabs, "FALLBACK_STATE_PATH", tmp_path / "fallback.json")
    challenge = {"challenge_id": "one"}
    monkeypatch.setattr(tabs, "_load_fallback_state", lambda: challenge)
    pages, opened = [], []
    monkeypatch.setattr(tabs, "list_cdp_targets", lambda _: pages)
    monkeypatch.setattr(tabs, "log_event", lambda _: None)

    def open_page(endpoint, url):
        opened.append(url)
        pages.append({"type": "page", "url": url})

    monkeypatch.setattr(tabs, "open_background_page", open_page)
    for _ in range(2):
        tabs.record_failed_drags("http://fixture", 1)
    assert not opened
    tabs.record_failed_drags("http://fixture", 1)
    assert opened == [url for _, url in tabs.SITES]
    tabs.record_failed_drags("http://fixture", 1)
    assert len(opened) == 2
    pages.pop()
    tabs.record_failed_drags("http://fixture", 1)
    assert opened[-1] == "https://www.baidu.com/"
    assert len(opened) == 3
    pages.clear()
    challenge["challenge_id"] = "two"
    tabs.record_failed_drags("http://fixture", 1)
    assert len(opened) == 3


def test_domain_matching_does_not_accept_lookalikes():
    assert tabs.site_present(
        [{"type": "page", "url": "https://www.google.com/search?q=x"}], "google.com"
    )
    for url in (
        "https://google.com.evil.test/",
        "https://notgoogle.com/",
        "about:blank",
    ):
        assert not tabs.site_present([{"type": "page", "url": url}], "google.com")


def test_existing_google_only_opens_baidu_and_error_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setattr(tabs, "FALLBACK_STATE_PATH", tmp_path / "fallback.json")
    monkeypatch.setattr(tabs, "_load_fallback_state", lambda: {"challenge_id": "one"})
    monkeypatch.setattr(
        tabs,
        "list_cdp_targets",
        lambda _: [{"type": "page", "url": "https://google.com/"}],
    )
    events = []
    monkeypatch.setattr(tabs, "log_event", events.append)

    def fail(endpoint, url):
        assert url == "https://www.baidu.com/"
        raise OSError("fixture")

    monkeypatch.setattr(tabs, "open_background_page", fail)
    tabs.record_failed_drags("http://fixture", 3)
    assert events[-1]["kind"] == "solver_reference_tab_error"
