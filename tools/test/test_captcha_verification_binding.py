"""Live success requires positive, ready, requested-target evidence, not teardown."""

import pytest

from tools.test.test_captcha_dom_evaluation import DocumentSolver

DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"
OTHER_DETAIL = "https://sf-item.taobao.com/sf_item/456.htm"
SEED = "https://sf.taobao.com/list/50025969__2.htm?location_code=110100&page=2"
DETAIL_HTML = '<html><body><div id="J_StartPrice">123</div></body></html>'
SEED_HTML = (
    '<html><body><script id="sf-item-list-data">{"data":[]}</script></body></html>'
)


def detail_document(**changes):
    return {
        "url": DETAIL,
        "text": "auction evidence " * 12,
        "html": DETAIL_HTML,
        **changes,
    }


@pytest.mark.parametrize(
    "document", [{}, {"url": DETAIL}, {"url": DETAIL, "readyState": "loading"}]
)
def test_live_teardown_is_not_success(document):
    assert DocumentSolver(document, target_url=DETAIL)._verify_success() is False


@pytest.mark.parametrize(
    "url,ready,target,expected",
    [
        (DETAIL, "complete", DETAIL, True),
        (DETAIL, "interactive", DETAIL, True),
        (DETAIL, "loading", DETAIL, False),
        (OTHER_DETAIL, "complete", DETAIL, False),
        (DETAIL, "complete", None, False),
        (DETAIL + "/_____tmd_____/punish", "complete", DETAIL, True),
        (DETAIL, "complete", DETAIL + "/_____tmd_____/punish", True),
        (
            "https://evil.invalid/sf-item.taobao.com/sf_item/123.htm",
            "complete",
            DETAIL,
            False,
        ),
    ],
)
def test_explicit_success_needs_ready_requested_target(url, ready, target, expected):
    solver = DocumentSolver(
        {"url": url, "readyState": ready, "text": "验证通过"}, target_url=target
    )
    assert solver._verify_success() is expected


@pytest.mark.parametrize(
    "selector", ["#nc_2_n1z", '[id^="nc_"][id$="_n1z"]', ".btn_slide", ".nc-slider-btn"]
)
def test_all_live_handle_selectors_block_explicit_success(selector):
    solver = DocumentSolver(
        {"url": DETAIL, "text": "验证通过", "nodes": [{"selectors": [selector]}]},
        DETAIL,
    )
    assert solver._verify_success() is False
    assert solver._page_challenge_summary()["authenticatedPage"] is False


@pytest.mark.parametrize(
    "frame", [{"text": "验证失败"}, {"nodes": [{"selectors": [".btn_slide"]}]}]
)
def test_visible_frame_vetoes_main_success_and_payload(frame):
    solver = DocumentSolver(
        detail_document(text="验证通过", frames=[{"document": frame}]), DETAIL
    )
    assert solver._verify_success() is False
    assert solver._page_challenge_summary()["authenticatedPage"] is False


def test_hidden_frame_does_not_replace_main_identity_or_payload():
    solver = DocumentSolver(
        detail_document(
            frames=[
                {"hidden": True, "document": {"url": OTHER_DETAIL, "text": "验证失败"}}
            ]
        ),
        DETAIL,
    )
    summary = solver._page_challenge_summary()
    assert summary["authenticatedPage"] is True
    assert summary["href"] == DETAIL
    assert summary["readyState"] == "complete"


@pytest.mark.parametrize(
    "changes,target,expected",
    [
        ({}, DETAIL, True),
        ({}, DETAIL + "/_____tmd_____/punish?x5secdata=private", True),
        ({"readyState": "interactive"}, DETAIL, True),
        ({"readyState": "loading"}, DETAIL, False),
        ({"url": OTHER_DETAIL}, DETAIL, False),
        ({"url": DETAIL + "/_____tmd_____/punish"}, DETAIL, False),
        (
            {"html": "<html><body>" + "auction evidence " * 20 + "</body></html>"},
            DETAIL,
            False,
        ),
        ({"html": DETAIL_HTML + "安全验证", "text": "安全验证"}, DETAIL, False),
        ({"url": "https://evil.invalid/?next=" + DETAIL}, DETAIL, False),
        ({}, None, False),
    ],
)
def test_detail_payload_is_structural_ready_and_target_bound(changes, target, expected):
    summary = DocumentSolver(
        detail_document(**changes), target
    )._page_challenge_summary()
    assert summary["authenticatedPage"] is expected
    assert summary["validAuctionPayload"] is expected


@pytest.mark.parametrize(
    "url,html,ready,expected",
    [
        (SEED, SEED_HTML, "complete", True),
        (SEED, SEED_HTML, "interactive", True),
        (SEED, SEED_HTML, "loading", False),
        (SEED.replace("110100", "310100"), SEED_HTML, "complete", False),
        (SEED.replace("page=2", "page=1"), SEED_HTML, "complete", False),
        (
            SEED,
            '<script id="sf-item-list-data">{incomplete</script>',
            "complete",
            False,
        ),
        (
            SEED,
            '<script id="sf-item-list-data">{"data":{}}</script>',
            "complete",
            False,
        ),
        (SEED, SEED_HTML + "安全验证", "complete", False),
        (SEED, SEED_HTML + "扫码登录", "complete", False),
        (SEED, "<html><body>normal links</body></html>", "complete", False),
    ],
)
def test_seed_accepts_empty_list_but_keeps_region_and_page_identity(
    url, html, ready, expected
):
    solver = DocumentSolver(
        {"url": url, "html": html, "readyState": ready}, SEED + "&x5secdata=private"
    )
    assert solver._page_challenge_summary()["authenticatedPage"] is expected


def test_raw_html_never_escapes_the_summary_or_refresh_fallback(monkeypatch):
    sentinel = "PRIVATE_HTML_SENTINEL"
    solver = DocumentSolver(detail_document(html=DETAIL_HTML + sentinel), DETAIL)
    summary = solver._page_challenge_summary()
    assert sentinel not in repr(summary)
    assert not any("html" in key.lower() for key in summary)
    monkeypatch.setattr(
        solver,
        "_page_challenge_summary",
        lambda: (_ for _ in ()).throw(RuntimeError("probe failed")),
    )
    refreshed = solver._refresh_challenge_summary(summary)
    assert refreshed["probeFailed"] is True
    assert sentinel not in repr(refreshed)


def test_polling_waits_for_bound_payload_instead_of_accepting_blank_teardown(
    monkeypatch,
):
    solver = DocumentSolver({"url": DETAIL}, DETAIL)
    solver._is_local_mock_slider_target = lambda: False
    solver._stop_if_cancelled = lambda: False
    waits = []

    def wait(seconds):
        waits.append(seconds)
        solver.document = detail_document()

    monkeypatch.setattr(solver, "_wait_interruptibly", wait, raising=False)
    assert solver._wait_for_verification_success(max_checks=2) is True
    assert len(waits) == 1


@pytest.mark.parametrize(
    "text",
    [
        "unsuccessful",
        "success rate",
        "安全验证 success",
        "auction evidence 验证通过",
        "安全验证 验证通过",
    ],
)
def test_generic_copy_is_not_explicit_verification_success(text):
    solver = DocumentSolver({"url": DETAIL, "text": text}, DETAIL)
    assert solver._verify_success() is False


@pytest.mark.parametrize("in_frame", [False, True])
def test_fixed_position_challenge_is_visible_even_without_offset_parent(in_frame):
    nodes = [{"selectors": [".btn_slide"], "fixed": True}]
    document = detail_document(text="验证通过")
    document.update(
        {"frames": [{"fixed": True, "document": {"nodes": nodes}}]}
        if in_frame
        else {"nodes": nodes}
    )
    solver = DocumentSolver(document, DETAIL)
    assert solver._verify_success() is False
    assert solver._page_challenge_summary()["authenticatedPage"] is False


def test_hidden_first_match_cannot_hide_a_second_visible_challenge():
    nodes = [
        {"selectors": [".btn_slide"], "hidden": True},
        {"selectors": [".btn_slide"]},
    ]
    solver = DocumentSolver(detail_document(text="验证通过", nodes=nodes), DETAIL)
    assert solver._verify_success() is False
    assert solver._page_challenge_summary()["authenticatedPage"] is False
