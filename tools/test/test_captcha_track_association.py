"""Real CDP expressions keep the selected handle, track and viewport together."""

import pytest

from tools.test.test_captcha_dom_evaluation import DocumentSolver, slider


def component(number, left, width, offset, *, parent_index=0):
    return [
        {
            "id": f"nc_{number}_n1t",
            "selectors": [f"#nc_{number}_n1t"],
            "rect": {"left": left, "width": width},
            "offsetWidth": width,
        },
        {
            "id": f"nc_{number}_n1z",
            "selectors": [f"#nc_{number}_n1z"],
            "rect": {"left": left + offset, "width": 30},
            "offsetLeft": offset,
            "offsetWidth": 30,
            "parent": parent_index,
            "offsetParentIndex": parent_index,
        },
    ]


def test_offset_handle_belongs_to_selected_component_not_dom_first_handle():
    solver = DocumentSolver(
        {
            "nodes": component(2, 500, 400, 20)
            + component(1, 100, 300, 10, parent_index=2)
        }
    )
    selected = solver._find_slider_once()
    assert selected["x"] == 110
    track = selected["track_rect"]
    assert (track["left"], track["width"], track["handleOffsetLeft"]) == (100, 300, 10)
    assert solver._remaining_drag_distance(selected, track, track["width"]) == 260
    assert solver._get_track_rect() == track


def test_iframe_slider_never_borrows_main_document_track():
    solver = DocumentSolver(
        {
            "nodes": [
                {"selectors": [".nc_scale"], "rect": {"left": 100, "width": 300}}
            ],
            "frames": [
                {"rect": {"left": 500}, "document": {"nodes": component(1, 0, 400, 20)}}
            ],
        }
    )
    selected = solver._find_slider_once()
    track = selected["track_rect"]
    assert selected["x"] == 520
    assert (track["left"], track["width"]) == (500, 400)
    assert solver._get_track_width() == 400
    assert solver._remaining_drag_distance(selected, track, 400) == 350


def test_iframe_borders_and_offsets_share_one_viewport_coordinate_space():
    solver = DocumentSolver(
        {
            "frames": [
                {
                    "rect": {"left": 300, "top": 40},
                    "clientLeft": 2,
                    "clientTop": 3,
                    "document": {"nodes": component(1, 20, 310, 3)},
                }
            ]
        }
    )
    selected = solver._find_slider_once()
    track = selected["track_rect"]
    assert (selected["x"], selected["y"]) == (325, 51)
    assert (track["left"], track["top"]) == (322, 51)
    assert solver._get_track_rect() == track


def test_offset_parent_outside_track_uses_viewport_residual_not_layout_offset():
    nodes = component(1, 100, 300, 10)
    nodes[1].pop("offsetParentIndex")
    nodes[1]["offsetLeft"] = 999
    solver = DocumentSolver({"nodes": nodes})
    selected = solver._find_slider_once()
    track = selected["track_rect"]
    assert track["handleOffsetLeft"] is None
    assert track["handleOffsetWidth"] is None
    assert solver._remaining_drag_distance(selected, track, 300) == 260


@pytest.mark.parametrize("mode", ["conflicting_id", "ambiguous", "other_container"])
def test_unknown_relationship_never_uses_an_unrelated_track(mode):
    if mode == "conflicting_id":
        nodes = [
            component(2, 500, 400, 20)[0],
            slider(id="nc_1_n1z", rect={"left": 100, "width": 30}),
        ]
    else:
        nodes = [
            {"selectors": [".nc-container"]},
            {"selectors": [".nc_scale"], "rect": {"width": 300}, "parent": 0},
            {"selectors": [".btn_slide"], "rect": {"width": 30}},
        ]
        if mode == "ambiguous":
            nodes.append({"selectors": [".nc_scale"], "rect": {"width": 400}})
    solver = DocumentSolver({"nodes": nodes})
    selected = solver._find_slider_once()
    assert selected["track_rect"] is None
    assert solver._get_track_rect() is None


@pytest.mark.parametrize(
    "mode",
    ["conflicting_ancestor", "conflicting_group", "duplicate_exact", "foreign_exact"],
)
def test_explicit_identity_and_ambiguity_apply_before_structural_association(mode):
    if mode == "conflicting_ancestor":
        nodes = component(2, 100, 400, 20)
        nodes[1]["id"] = "nc_1_n1z"
        nodes[1]["selectors"] = ["#nc_1_n1z"]
    elif mode == "conflicting_group":
        nodes = [
            {"selectors": [".nc-container"]},
            {**component(2, 100, 400, 20)[0], "parent": 0},
            slider(id="nc_1_n1z", parent=0, rect={"width": 30}),
        ]
    elif mode == "duplicate_exact":
        nodes = component(1, 100, 400, 20) + [component(1, 600, 300, 0)[0]]
    else:
        nodes = [
            {"selectors": [".nc-container"]},
            {**component(1, 100, 400, 20)[0], "parent": 0},
            {"selectors": [".nc-container"]},
            slider(id="nc_1_n1z", parent=2, rect={"width": 30}),
        ]
    solver = DocumentSolver({"nodes": nodes})
    assert solver._find_slider_once()["track_rect"] is None
    assert solver._get_track_rect() is None


def test_unique_generic_siblings_keep_rect_but_not_unproven_offsets():
    solver = DocumentSolver(
        {
            "nodes": [
                {"selectors": [".nc_scale"], "rect": {"left": 100, "width": 300}},
                {
                    "selectors": [".slider-btn"],
                    "rect": {"left": 110, "width": 30},
                    "offsetLeft": 999,
                },
            ]
        }
    )
    selected = solver._find_slider_once()
    assert selected["track_rect"]["width"] == 300
    assert selected["track_rect"]["handleOffsetLeft"] is None


def test_mock_track_keeps_selected_mock_handle_even_outside_nc_handle_selectors():
    solver = DocumentSolver(
        {
            "nodes": [
                {
                    "selectors": ["#mock-slider-track", ".nc_scale"],
                    "rect": {"width": 300},
                },
                {
                    "selectors": ["#mock-slider-handle"],
                    "parent": 0,
                    "offsetParentIndex": 0,
                    "rect": {"width": 30},
                    "offsetLeft": 4,
                    "offsetWidth": 30,
                },
            ]
        }
    )
    assert solver._find_slider_once()["track_rect"]["handleOffsetLeft"] == 4


def test_atomic_geometry_has_no_additional_cdp_scan(monkeypatch):
    solver = DocumentSolver({"nodes": component(1, 100, 300, 10)})
    selected = solver._find_slider_once()

    def forbidden():
        pytest.fail("Atomic geometry must not scan another component")

    monkeypatch.setattr(solver, "_get_track_rect", forbidden)
    monkeypatch.setattr(solver, "_get_track_width", forbidden)
    assert solver._slider_track_geometry(selected) == (300, selected["track_rect"])
