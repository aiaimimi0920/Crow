"""Explicit NC completion must not veto itself, nor hide another live challenge."""

import pytest

from tools.test.test_captcha_dom_evaluation import DocumentSolver

DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"


def completed_document(*children, **changes):
    return {
        "url": DETAIL,
        "nodes": [
            {
                "selectors": [".nc-container", ".nc-container.nc-success"],
                "className": "nc-container nc-success",
            },
            *children,
        ],
        **changes,
    }


@pytest.mark.parametrize(
    "children",
    [
        [],
        [{"selectors": [".nc_wrapper"], "parent": 0}],
        [{"selectors": ["#nc_1_n1t", ".nc_scale"], "parent": 0}],
        [
            {"selectors": [".nc_wrapper"], "parent": 0},
            {"selectors": ["#nc_1_n1z", ".btn_slide"], "parent": 1, "hidden": True},
        ],
    ],
)
def test_visible_completed_widget_is_positive_evidence_not_an_active_challenge(
    children,
):
    solver = DocumentSolver(completed_document(*children), DETAIL)
    assert solver._verify_success() is True
    assert solver._page_challenge_summary()["challengePresent"] is False


@pytest.mark.parametrize(
    "selector", [".btn_slide", ".slider-btn", ".icon-slide-arrow", ".errloading"]
)
def test_success_marker_never_hides_visible_controls_or_errors(selector):
    solver = DocumentSolver(
        completed_document({"selectors": [selector], "parent": 0}), DETAIL
    )
    assert solver._verify_success() is False
    assert solver._page_challenge_summary()["authenticatedPage"] is False


@pytest.mark.parametrize(
    "selector", [".nc-container", ".nc_scale", ".btn_slide", ".errloading"]
)
def test_other_live_widget_still_vetoes_completed_container(selector):
    solver = DocumentSolver(completed_document({"selectors": [selector]}), DETAIL)
    assert solver._verify_success() is False


def test_nested_unfinished_container_cannot_inherit_parent_success():
    solver = DocumentSolver(
        completed_document({"selectors": [".nc-container"], "parent": 0}), DETAIL
    )
    assert solver._verify_success() is False


@pytest.mark.parametrize(
    "changes,target",
    [
        ({"url": DETAIL.replace("123", "456")}, DETAIL),
        ({"readyState": "loading"}, DETAIL),
        ({}, None),
        ({"text": "验证失败"}, DETAIL),
        (
            {"frames": [{"document": {"nodes": [{"selectors": [".btn_slide"]}]}}]},
            DETAIL,
        ),
    ],
)
def test_completed_marker_keeps_target_readiness_error_and_frame_guards(
    changes, target
):
    assert (
        DocumentSolver(completed_document(**changes), target)._verify_success() is False
    )


def test_completed_widget_does_not_hide_valid_bound_auction_payload():
    solver = DocumentSolver(
        completed_document(
            html='<html><body><div id="J_StartPrice">123</div></body></html>'
        ),
        DETAIL,
    )
    assert solver._page_challenge_summary()["authenticatedPage"] is True


def test_completed_frame_alone_cannot_supply_main_document_success():
    solver = DocumentSolver(
        {"url": DETAIL, "frames": [{"document": completed_document()}]}, DETAIL
    )
    assert solver._verify_success() is False


def test_hidden_first_container_does_not_mask_visible_completed_container():
    document = completed_document()
    document["nodes"].insert(0, {"selectors": [".nc-container"], "hidden": True})
    assert DocumentSolver(document, DETAIL)._verify_success() is True
