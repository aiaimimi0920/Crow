"""An invisible ancestor must not expose stale challenge controls or errors."""

import pytest

from tools.test.test_captcha_dom_evaluation import DocumentSolver
from tools.test.test_captcha_nc_success_verification import DETAIL, completed_document


@pytest.mark.parametrize("selector", [".errloading", ".btn_slide", ".nc_scale"])
@pytest.mark.parametrize("depth", [1, 2])
def test_transparent_ancestor_cannot_veto_a_visible_completed_widget(selector, depth):
    nodes = [{"selectors": [], "style": {"opacity": "0"}}]
    for _ in range(depth - 1):
        nodes.append({"selectors": [], "parent": len(nodes)})
    nodes.append({"selectors": [selector], "parent": len(nodes)})
    solver = DocumentSolver(completed_document(*nodes), DETAIL)
    assert solver._verify_success() is True
    summary = solver._page_challenge_summary()
    assert summary["challengePresent"] is False


@pytest.mark.parametrize("selector", [".errloading", ".btn_slide"])
def test_transparent_child_group_inside_completed_widget_is_not_active(selector):
    solver = DocumentSolver(
        completed_document(
            {"selectors": [], "style": {"opacity": "0"}, "parent": 0},
            {"selectors": [selector], "parent": 1},
        ),
        DETAIL,
    )
    assert solver._verify_success() is True


@pytest.mark.parametrize("opacity", ["0.01", "0.5", "1"])
def test_nonzero_opacity_must_not_hide_an_active_challenge(opacity):
    solver = DocumentSolver(
        completed_document(
            {"selectors": [], "style": {"opacity": opacity}},
            {"selectors": [".btn_slide"], "parent": 1},
        ),
        DETAIL,
    )
    assert solver._verify_success() is False


def test_transparent_success_container_is_not_positive_evidence():
    document = completed_document()
    document["nodes"][0]["parent"] = 1
    document["nodes"].append({"selectors": [], "style": {"opacity": "0"}})
    assert DocumentSolver(document, DETAIL)._verify_success() is False


@pytest.mark.parametrize(
    "method", ["_find_slider_once", "_get_track_rect", "_nc_widget_rect"]
)
def test_control_lookup_skips_the_transparent_ancestor_group(method):
    solver = DocumentSolver(
        {
            "nodes": [
                {"selectors": [], "style": {"opacity": "0"}},
                {"selectors": [".btn_slide", ".nc_scale"], "parent": 0},
                {"selectors": [".btn_slide", ".nc_scale"], "rect": {"left": 100}},
            ]
        }
    )
    result = getattr(solver, method)()
    assert result["x" if method != "_get_track_rect" else "left"] == 100


def test_retry_lookup_does_not_click_a_transparent_error_group():
    solver = DocumentSolver(
        {
            "nodes": [
                {"selectors": [], "style": {"opacity": "0"}},
                {"selectors": [".errloading"], "parent": 0},
            ]
        }
    )
    assert solver._nc_retry_targets()["retryText"] is None
