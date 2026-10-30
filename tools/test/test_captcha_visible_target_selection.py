"""Find eligible visible controls, not stale first matches or hidden-frame controls."""

import pytest

from tools.test.test_captcha_dom_evaluation import DocumentSolver


def node(selector, left, **changes):
    return {"selectors": [selector], "rect": {"left": left}, **changes}


@pytest.mark.parametrize("ineligible", [{"hidden": True}, {"rect": {"width": 5}}])
def test_slider_skips_ineligible_first_match_with_same_selector(ineligible):
    solver = DocumentSolver(
        {"nodes": [node(".btn_slide", 1, **ineligible), node(".btn_slide", 100)]}
    )
    assert solver._find_slider_once()["x"] == 100


def test_fixed_position_slider_is_a_visible_candidate():
    solver = DocumentSolver({"nodes": [node(".btn_slide", 100, fixed=True)]})
    assert solver._find_slider_once()["x"] == 100


def test_slider_never_selects_hidden_frame_before_visible_frame():
    solver = DocumentSolver(
        {
            "frames": [
                {"hidden": True, "document": {"nodes": [node(".btn_slide", 1)]}},
                {
                    "rect": {"left": 50, "top": 70},
                    "document": {"nodes": [node(".btn_slide", 100)]},
                },
            ]
        }
    )
    result = solver._find_slider_once()
    assert (result["context"], result["x"], result["y"]) == ("iframe", 150, 78)


@pytest.mark.parametrize("method", ["_get_track_width", "_get_track_rect"])
@pytest.mark.parametrize("ineligible", [{"hidden": True}, {"rect": {"width": 50}}])
def test_track_lookup_skips_ineligible_first_match(method, ineligible):
    solver = DocumentSolver(
        {
            "nodes": [
                node(".nc_scale", 1, **ineligible),
                node(".nc_scale", 100, rect={"left": 100, "width": 310}),
            ]
        }
    )
    result = getattr(solver, method)()
    assert (result if method == "_get_track_width" else result["width"]) == 310


def test_track_rect_uses_visible_handle_offsets_not_hidden_first_handle():
    solver = DocumentSolver(
        {
            "nodes": [
                node(".nc_scale", 100, offsetWidth=310),
                node(".btn_slide", 1, hidden=True, offsetLeft=200, offsetWidth=1),
                node(
                    ".btn_slide",
                    100,
                    parent=0,
                    offsetParentIndex=0,
                    offsetLeft=3,
                    offsetWidth=30,
                ),
            ]
        }
    )
    result = solver._get_track_rect()
    assert (result["handleOffsetLeft"], result["handleOffsetWidth"]) == (3, 30)


@pytest.mark.parametrize("method", ["_get_track_width", "_get_track_rect"])
def test_track_lookup_does_not_read_hidden_iframe(method):
    solver = DocumentSolver(
        {"frames": [{"hidden": True, "document": {"nodes": [node(".nc_scale", 1)]}}]}
    )
    assert getattr(solver, method)() == (340 if method == "_get_track_width" else None)


@pytest.mark.parametrize("ineligible", [{"hidden": True}, {"rect": {"width": 7}}])
def test_widget_rect_skips_ineligible_first_widget(ineligible):
    solver = DocumentSolver(
        {"nodes": [node(".nc_scale", 1, **ineligible), node(".nc_scale", 100)]}
    )
    assert solver._nc_widget_rect()["x"] == 100


@pytest.mark.parametrize("ineligible", [{"hidden": True}, {"rect": {"width": 7}}])
def test_retry_targets_select_visible_eligible_matches(ineligible):
    nodes = []
    for selector in (".nc_scale", ".btn_slide", ".errloading"):
        nodes.extend([node(selector, 1, **ineligible), node(selector, 100)])
    result = DocumentSolver({"nodes": nodes})._nc_retry_targets()
    assert {key: result[key]["x"] for key in ("widget", "slider", "retryText")} == {
        "widget": 100,
        "slider": 100,
        "retryText": 100,
    }


def test_fixed_position_widget_and_retry_targets_remain_eligible():
    solver = DocumentSolver(
        {
            "nodes": [
                node(selector, 100, fixed=True)
                for selector in (".nc_scale", ".errloading")
            ]
        }
    )
    assert solver._nc_widget_rect()["x"] == 100
    assert solver._nc_retry_targets()["retryText"]["x"] == 100


def test_explicit_selector_priority_and_first_eligible_match_are_preserved():
    solver = DocumentSolver(
        {
            "nodes": [
                node(".btn_slide", 1),
                node("#nc_1_n1z", 100),
                node("#nc_1_n1z", 200),
            ]
        }
    )
    result = solver._find_slider_once()
    assert (result["selector"], result["x"]) == ("#nc_1_n1z", 100)
