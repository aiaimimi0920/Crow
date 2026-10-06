from pathlib import Path


SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_target.py")
SLIDER_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_slider.py")
CDP_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_cdp.py")
PREFLIGHT_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_preflight.py")
FALLBACKS_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_fallbacks.py")
NC_RETRY_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_nc_retry.py")
OS_MAPPING_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_os_mapping.py")
OS_INPUT_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_os_input.py")
OS_WINDOWS_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_os_windows.py")
ORCHESTRATION_SOURCE = Path(__file__).parents[2].joinpath("src", "captcha_orchestration.py")


def test_captcha_target_runtime_messages_use_structured_logging() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert "logger.exception(\"[SOLVER] Cancel checker failed\")" in source
    assert "logger.warning(\"[SOLVER] Failed to fetch /json/%s: %s\"" in source
    assert "logger.info(\"[SOLVER] Opened target with browser identity installed before navigation.\")" in source
    assert "print(" not in source


def test_captcha_slider_runtime_messages_use_structured_logging() -> None:
    source = SLIDER_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.info("[SOLVER] Slider not found; retrying attempt=%s/%s"' in source
    assert 'logger.warning("[SOLVER] Could not detect track width; using fallback 340px")' in source
    assert 'logger.warning("[SOLVER] CDP mouse input is unavailable; returning to bounded retry.")' in source
    assert "print(" not in source


def test_captcha_cdp_request_failures_use_structured_logging() -> None:
    source = CDP_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.error("[SOLVER] CDP Error method=%s error=%s"' in source
    assert 'logger.warning("[SOLVER] Timeout waiting for %s"' in source
    assert 'logger.warning("[SOLVER] Error receiving response method=%s: %s"' in source
    assert 'logger.error("[SOLVER] CDP Send Error method=%s: %s"' in source
    assert 'logger.warning("[SOLVER] Failed to activate target tab %s: %s"' in source
    assert 'logger.info("[SOLVER] Currently open tabs:")' in source
    assert "print(" not in source


def test_captcha_preflight_messages_use_structured_logging() -> None:
    source = PREFLIGHT_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.warning("[SOLVER] Challenge preflight failed: %s"' in source
    assert 'logger.info("[SOLVER] Login page detected; waiting for QR/manual login to complete.")' in source
    assert 'logger.warning("[SOLVER] Unsupported hard block detected; manual verification required.")' in source
    assert "print(" not in source


def test_captcha_fallback_messages_use_structured_logging() -> None:
    source = FALLBACKS_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.info("[SOLVER] Starting Playwright Stealth...")' in source
    assert 'logger.exception("[SOLVER] Playwright Stealth error")' in source
    assert 'logger.exception("[SOLVER] OpenCV error")' in source
    assert "print(" not in source


def test_captcha_nc_retry_messages_use_structured_logging() -> None:
    source = NC_RETRY_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.warning("[SOLVER] NC retry widget not found.")' in source
    assert 'logger.info("[SOLVER] NC retry click recovered an authenticated page.")' in source
    assert 'logger.warning("[SOLVER] NC retry click did not restore a slider.")' in source
    assert "print(" not in source


def test_captcha_os_mapping_messages_use_structured_logging() -> None:
    source = OS_MAPPING_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.warning("[SOLVER] Screenshot locate failed: %s"' in source
    assert 'logger.warning("[SOLVER] Screen mapping unavailable; skipping OS drag.")' in source
    assert 'logger.warning("[SOLVER] Linux slider mapping requires screenshot or X11 geometry verification.")' in source
    assert "print(" not in source


def test_captcha_os_input_messages_use_structured_logging() -> None:
    source = OS_INPUT_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.warning("[SOLVER] Screen mapping failed: %s"' in source
    assert 'logger.warning("[SOLVER] Slider screenshot mapping could not be verified; skipping OS drag.")' in source
    assert 'logger.exception("[SOLVER] OS mouse drag failed")' in source
    assert "print(" not in source


def test_captcha_os_windows_messages_use_structured_logging() -> None:
    source = OS_WINDOWS_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.warning("[SOLVER] SetForegroundWindow failed: %s"' in source
    assert 'logger.warning("[SOLVER] No focusable Linux Chromium window was found.")' in source
    assert 'logger.info("[SOLVER] OS window focus hwnd=%s focused=%s"' in source
    assert "print(" not in source


def test_captcha_orchestration_fallback_selection_uses_structured_logging() -> None:
    source = ORCHESTRATION_SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.info("[SOLVER] Attempting ddddocr AI识别...")' in source
    assert 'logger.exception("[SOLVER] ddddocr error")' in source
    assert 'logger.info("[SOLVER] Using CDP method...")' in source
    assert 'logger.info("[SOLVER] Attempt %s/%s"' in source
    assert 'logger.warning("[SOLVER] connect_tab failed; retrying in 5 seconds")' in source
    assert 'logger.warning("[SOLVER] Unsupported hard block detected; manual verification required.")' in source
    assert 'logger.exception("[SOLVER] Error during steps")' in source
    assert 'logger.warning("[SOLVER] Max attempts (%s) reached without success"' in source
    assert "print(" not in source
