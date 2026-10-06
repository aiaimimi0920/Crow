"""Known auction targets cannot borrow authentication from unrelated tabs."""

import pytest

from src.captcha_target import CaptchaTargetMixin
from tools import pc2_local_solver, pc2_solver_cdp, pc2_solver_loop_control

DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"
SEED = "https://sf.taobao.com/list/50025969__2.htm?location_code=510302&page=18"
ENDPOINT = "http://browser.test:9224"
HEALTHY = {"authenticatedPage": True, "challengePresent": False}


@pytest.fixture
def probe(monkeypatch):
    connections = []
    pages = []
    summaries = {}

    class FakeSolver:
        _normalize_target_url = CaptchaTargetMixin._normalize_target_url
        _solver_target_route = CaptchaTargetMixin._solver_target_route

        def __init__(self, **_kwargs):
            self.target = None

        def _remember_target_tab(self, tab):
            self.target = tab["id"]

        def _connect_to_target(self, *_args):
            connections.append(self.target)
            return True

        def _page_challenge_summary(self):
            return summaries.get(self.target, HEALTHY)

        def _close_solver_ws(self):
            pass

    def add(url, summary=None, *, target_id="other"):
        pages.append(
            {
                "id": target_id,
                "type": "page",
                "url": url,
                "webSocketDebuggerUrl": "ws://browser.test/" + target_id,
            }
        )
        summaries[target_id] = HEALTHY if summary is None else summary

    monkeypatch.setattr(pc2_solver_cdp, "_create_probe_solver", FakeSolver)
    monkeypatch.setattr(pc2_solver_cdp, "fetch_json", lambda *_args, **_kwargs: pages)
    return add, connections


@pytest.mark.parametrize("module", [pc2_solver_cdp, pc2_local_solver])
@pytest.mark.parametrize(
    "other_url",
    [
        SEED,
        DETAIL.replace("123.htm", "456.htm"),
        "https://sf.taobao.com/",
        "https://example.test/healthy",
    ],
)
def test_missing_detail_never_borrows_another_pages_authentication(
    probe, module, other_url
):
    add, connections = probe
    add(other_url)

    assert module.check_cdp_browser_for_authenticated_target(ENDPOINT, DETAIL) is None
    assert connections == []


@pytest.mark.parametrize("module", [pc2_solver_cdp, pc2_local_solver])
@pytest.mark.parametrize(
    "other_url",
    [
        DETAIL,
        SEED.replace("page=18", "page=19"),
        SEED.replace("location_code=510302", "location_code=510303"),
    ],
)
def test_seed_still_requires_its_complete_target_identity(probe, module, other_url):
    add, connections = probe
    add(other_url)

    assert module.check_cdp_browser_for_authenticated_target(ENDPOINT, SEED) is None
    assert connections == []


@pytest.mark.parametrize(
    "url", [DETAIL, DETAIL + "?track_id=background&__captcha_solver_bg=1"]
)
def test_matching_healthy_detail_still_provides_authentication(probe, url):
    add, connections = probe
    add(url, target_id="current")
    add(SEED)

    result = pc2_solver_cdp.check_cdp_browser_for_authenticated_target(ENDPOINT, DETAIL)

    assert result == {"_target_id": "current", "_target_url": url}
    assert connections == ["current"]


def test_matching_detail_challenge_cannot_be_overridden_by_healthy_other_tab(probe):
    add, connections = probe
    add(
        DETAIL + "/_____tmd_____/punish?x5step=1",
        {"authenticatedPage": False, "challengePresent": True},
        target_id="challenge",
    )
    add(SEED)

    assert (
        pc2_solver_cdp.check_cdp_browser_for_authenticated_target(ENDPOINT, DETAIL)
        is None
    )
    assert connections == ["challenge"]


def test_legacy_unknown_scope_keeps_session_fallback(probe):
    add, connections = probe
    add("https://example.test/healthy", target_id="legacy")

    result = pc2_solver_cdp.check_cdp_browser_for_authenticated_target(
        ENDPOINT, "https://example.test/requested"
    )

    assert result["_target_id"] == "legacy"
    assert connections == ["legacy"]


@pytest.mark.parametrize("other_url", [SEED, DETAIL.replace("123.htm", "456.htm")])
def test_missing_detail_recovery_rebuilds_target_without_submitting_completion(
    probe, monkeypatch, other_url
):
    add, connections = probe
    add(other_url)
    completions, rebuilds = [], []
    monkeypatch.setattr(
        pc2_solver_loop_control, "_recent_healthy_auth_snapshot", lambda _: False
    )
    monkeypatch.setattr(pc2_solver_loop_control, "log_event", lambda _: None)
    monkeypatch.setattr(
        pc2_solver_loop_control,
        "_mark_auth_complete_pending",
        lambda *args, **kwargs: completions.append((args, kwargs)) or {},
    )
    monkeypatch.setattr(
        pc2_solver_loop_control,
        "_retry_pending_auth_confirmation",
        lambda *args, **kwargs: {"pending": True, "confirmed": False},
    )
    monkeypatch.setattr(
        pc2_solver_loop_control,
        "rebuild_missing_challenge_target",
        lambda endpoint, url: (
            rebuilds.append((endpoint, url))
            or {"probe_target": {"_target_id": "rebuilt-current"}}
        ),
    )
    status = {
        "scope": "detail",
        "challenge_id": "detail-current",
        "paused": True,
        "last_request": {
            "node_id": "pc2",
            "target_url": DETAIL,
            "cdp_endpoint": ENDPOINT,
        },
    }

    result = pc2_solver_loop_control.recover_stale_pause(
        "http://api.test", ENDPOINT, status, [DETAIL], "pc2", 0.0
    )

    assert completions == []
    assert rebuilds == [(ENDPOINT, DETAIL)]
    assert result["last_probe_target"] == {"_target_id": "rebuilt-current"}
    assert connections == []
