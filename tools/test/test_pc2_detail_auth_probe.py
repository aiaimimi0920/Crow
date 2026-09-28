import hashlib
from types import SimpleNamespace

import pytest

from tools import pc2_auth_recovery as pc2
from tools.pc2_detail_auth_probe import (
    detail_payload_authenticated,
    probe_detail_access,
)
from tools.test.test_stage_auth_recovery import DETAIL, recovery

HTML = '<html><input id="J_StartPrice" value="123"></html>'


@pytest.mark.parametrize(
    "html,url,expected",
    [
        (HTML, DETAIL, True),
        ("", DETAIL, False),
        (HTML + "x5secdata=blocked", DETAIL, False),
        (HTML, "https://login.taobao.com/", False),
        (HTML, "https://sf-item.taobao.com/sf_item/999.htm", False),
    ],
)
def test_detail_proof_requires_same_item_and_real_unblocked_payload(
    html, url, expected
):
    assert detail_payload_authenticated(html, url, DETAIL) is expected


@pytest.mark.parametrize(
    "mode", ["healthy", "challenge", "http_error", "exception", "empty"]
)
def test_probe_uses_fresh_owned_page_and_preserves_browser(monkeypatch, mode):
    import playwright.sync_api

    calls = []

    class Page:
        url = DETAIL

        def goto(self, url, **kwargs):
            calls.append(("goto", url))
            if mode == "exception":
                raise OSError("navigation failed")
            return SimpleNamespace(status=503 if mode == "http_error" else 200)

        def content(self):
            return (
                HTML
                if mode == "healthy"
                else ("x5secdata=blocked" if mode == "challenge" else "")
            )

        def wait_for_timeout(self, _):
            pass

        def close(self):
            calls.append("close_owned_page")

    class Browser:
        contexts = [
            SimpleNamespace(new_page=lambda: calls.append("new_page") or Page())
        ]

        def close(self):
            pytest.fail("must not close the external browser")

    class Playwright:
        chromium = SimpleNamespace(connect_over_cdp=lambda *a, **k: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", Playwright)
    if mode == "exception":
        with pytest.raises(OSError):
            probe_detail_access("http://fixture", DETAIL)
    else:
        assert probe_detail_access("http://fixture", DETAIL) is (mode == "healthy")
    assert calls == ["new_page", ("goto", DETAIL), "close_owned_page"]


@pytest.mark.parametrize("probe_result", ["healthy", "challenge", "unavailable"])
def test_detail_receipt_only_clears_challenge_after_actual_probe(
    tmp_path, monkeypatch, probe_result
):
    manager, _ = recovery(tmp_path, scope="detail")
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        '[{"name":"cookie2","value":"fixture","domain":".taobao.com"}]'
    )
    digest = hashlib.sha256(cookie_file.read_bytes()).hexdigest()
    with manager._locked_state():
        manager._state["active"]["snapshot"]["sha256"] = digest
        manager._persist_locked()
    token = tmp_path / "token"
    token.write_text("fixture-recovery-token-0001")
    monkeypatch.setattr(
        pc2,
        "import_cookie_snapshot_to_cdp",
        lambda *a, **k: {"sha256": digest, "cookie_count": 1},
    )
    probes, cleared = [], []

    def probe(endpoint, target):
        probes.append(target)
        if probe_result == "unavailable":
            raise OSError("private network details")
        return probe_result == "healthy"

    monkeypatch.setattr(pc2, "probe_detail_access", probe)

    def post(url, payload, **kwargs):
        if url.endswith("/heartbeat"):
            return {"ok": True}
        assert url.endswith("/result")
        return manager.accept_stage_result(
            payload,
            validate_and_clear=lambda a: cleared.append(a["scope"]),
            captured_count=10,
            now=8,
        )

    result = pc2.process_nas_auth_recovery_once(
        "http://fixture/api",
        "http://fixture/cdp",
        "pc2",
        cookie_file,
        tmp_path / "marker",
        token,
        fetcher=lambda *a, **k: {"auth_recovery": manager.snapshot(now=7)},
        poster=post,
    )
    assert probes == [DETAIL]
    assert cleared == (["detail"] if probe_result == "healthy" else [])
    state = manager.snapshot(now=9)
    if probe_result == "healthy":
        assert result["action"] == "recovery_verifying"
        assert state["active"]["status"] == "verifying"
        assert state["last_result"] is None
        manager.sample(11, 99, now=10)
        assert manager.snapshot(now=11)["last_result"]["status"] == "succeeded"
    else:
        assert result["action"] == "recovery_failed"
        assert state["last_result"]["reason"] == (
            "stage_probe_failed"
            if probe_result == "challenge"
            else "stage_probe_unavailable"
        )
