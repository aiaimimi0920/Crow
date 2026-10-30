"""Focus remeasurement consumes an exact expiring node/track reference, not a selector."""

import json

import pytest

from src.captcha_dom import SLIDER_SELECTORS, TRACK_SELECTORS, eval_in_all_frames
from src.captcha_os_target import _INSTALL, OSPointerTarget
from src.captcha_slider_geometry import GEOMETRY_HELPERS, geometry_expression
from tools.test.test_captcha_dom_evaluation import DocumentSolver
from tools.test.test_captcha_os_target import make_probe, pointer_event, snapshot
from tools.test.test_captcha_track_association import component


def installation():
    return eval_in_all_frames(
        _INSTALL.replace("__KEY__", json.dumps("__test_probe"))
        .replace("__SELECTOR__", json.dumps("#nc_1_n1z"))
        .replace("__CONTEXT__", json.dumps("iframe"))
        .replace("__BINDING_KEY__", json.dumps("__test_anchor"))
        .replace("__GEOMETRY_HELPERS__", GEOMETRY_HELPERS)
    )


def run_binding(document, mutation="", after_install=""):
    find = eval_in_all_frames(
        geometry_expression(
            SLIDER_SELECTORS, TRACK_SELECTORS, binding_key="__test_anchor"
        )
    )
    expression = "(function(){var selected=(" + find + ");" + mutation
    expression += (
        "var retained=window.__test_anchor, installed=(" + installation() + ");"
    )
    expression += after_install
    expression += "return {selected:selected, snapshot:"
    expression += "window.__test_probe.read()" if after_install else "installed"
    expression += ", consumed:!window.__test_anchor};})()"
    return DocumentSolver(document)._send_cdp(
        "Runtime.evaluate", {"expression": expression}
    )["result"]["value"]


def test_focus_remeasurement_stays_in_bound_frame_when_earlier_frame_becomes_eligible():
    result = run_binding(
        {
            "frames": [
                {
                    "rect": {"left": 100},
                    "document": {
                        "nodes": [
                            {
                                "id": "nc_1_n1z",
                                "selectors": ["#nc_1_n1z"],
                                "rect": {"width": 5},
                            },
                        ]
                    },
                },
                {
                    "rect": {"left": 500},
                    "clientLeft": 2,
                    "document": {"nodes": component(1, 0, 400, 20)},
                },
            ]
        },
        "document.getElementsByTagName('iframe')[0].contentDocument.getElementById('nc_1_n1z').rect.width=40;",
    )
    assert result["selected"]["x"] == 522
    assert result["snapshot"]["rect"]["x"] == 522
    assert result["snapshot"]["track_rect"]["left"] == 502
    assert result["snapshot"]["geometry_bound"] is True
    assert result["consumed"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "delete window.__test_anchor;",
        "window.__test_anchor.node.isConnected=false;",
        "window.__test_anchor.track.isConnected=false;",
        "window.__test_anchor.track.hidden=true;",
        "window.__test_anchor.track.rect.width=40;",
        "Object.defineProperty(window.__test_anchor.frame,'contentDocument',{value:{}});",
        "window.__test_anchor.node.parentElement=null;",
        "window.__test_anchor.node.id='nc_2_n1z';",
        "window.__test_anchor.track.id='nc_2_n1t';",
        "window.__test_anchor.expiresAt=0;",
    ],
)
def test_expired_or_detached_binding_never_falls_back_to_available_selector(mutation):
    result = run_binding(
        {"frames": [{"document": {"nodes": component(1, 0, 400, 20)}}]}, mutation
    )
    assert not OSPointerTarget._valid(result["snapshot"])


@pytest.mark.parametrize("phase", ["before_install", "before_press"])
@pytest.mark.parametrize("change", ["node_parent", "track_parent", "group", "expiry"])
def test_relationship_changes_invalidate_binding_without_selecting_another_track(
    phase, change
):
    nodes = component(1, 0, 400, 20) + [
        {"id": "wrapper", "selectors": ["#wrapper"]},
        {"id": "foreign", "selectors": ["#foreign", ".nc-container"]},
    ]
    nodes[0]["parent"] = 2
    changes = {
        "node_parent": "node.parentElement=null;",
        "track_parent": "track.parentElement=null;",
        "group": "track.parentElement.parentElement=document.getElementById('foreign');",
        "expiry": "expiresAt=0;",
    }
    if phase == "before_install":
        result = run_binding(
            {"nodes": nodes}, "window.__test_anchor." + changes[change]
        )
    else:
        result = run_binding(
            {"nodes": nodes}, after_install="retained." + changes[change]
        )
    assert not OSPointerTarget._valid(result["snapshot"])


@pytest.mark.parametrize("phase", ["before_install", "before_press"])
def test_intermediate_ancestor_reparent_cannot_keep_an_unrelated_bound_track(phase):
    nodes = component(1, 0, 400, 20) + [
        {"selectors": [], "parent": 0},
    ]
    nodes[1]["parent"] = 2
    change = "node.parentElement.parentElement=null;"
    result = run_binding(
        {"nodes": nodes},
        "window.__test_anchor." + change if phase == "before_install" else "",
        "retained." + change if phase == "before_press" else "",
    )
    assert not OSPointerTarget._valid(result["snapshot"])


@pytest.mark.parametrize(
    "change", ["width", "left", "handleOffsetLeft", "missing", "invalid"]
)
def test_track_change_after_open_blocks_press_even_with_stable_handle(
    monkeypatch, change
):
    before, after = snapshot(), snapshot(pointer_event())
    track = {
        "left": 100,
        "top": 150,
        "width": 300,
        "height": 30,
        "offsetWidth": 300,
        "handleOffsetLeft": 10,
        "handleOffsetWidth": 40,
    }
    before.update(geometry_bound=True, track_rect=track)
    after.update(geometry_bound=True, track_rect=dict(track))
    if change == "missing":
        after["track_rect"] = None
    elif change == "invalid":
        after["track_rect"]["width"] = "invalid"
    else:
        after["track_rect"][change] += 20
    probe, solver, _calls, moves = make_probe(monkeypatch, [before, after])
    probe.info = {**probe.info, "binding_key": "__test_anchor"}
    assert probe.open()
    assert probe.verify(None, {"x": 236, "y": 197}) is None
    assert solver.last_failure_reason == "screen_mapping_target_changed"
    assert moves == []
