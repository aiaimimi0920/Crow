"""CSS element scaling and physical DPR are distinct input conversions."""

from types import SimpleNamespace

import pytest

from tools.test.test_captcha_release_hold import make_drag


@pytest.mark.parametrize("element_scale", [0.5, 1, 2])
@pytest.mark.parametrize("dpr", [1, 1.5, 2])
@pytest.mark.parametrize("bound", [False, True])
def test_fresh_os_probe_converts_layout_then_dpr_once(
    monkeypatch, element_scale, dpr, bound
):
    solver, pointer, _drag = make_drag(monkeypatch, "os")
    track_width = 300 * element_scale
    handle = {
        "x": 100 + 100 * element_scale,
        "y": 30,
        "width": 42 * element_scale,
        "height": 40,
    }
    track = {
        "left": 100,
        "width": track_width,
        "offsetWidth": 300,
        "handleOffsetWidth": 42,
        "handleOffsetLeft": 100,
    }
    probe = SimpleNamespace(
        enabled=True,
        rect=handle,
        point=(handle["x"] + handle["width"] / 2, 50),
        scale=dpr,
        geometry_bound=bound,
        track_rect=track,
        open=lambda: True,
        verify=lambda *_: (100, 50),
    )
    mapped_distances = []

    def mapping(_x, _y, distance, **_kwargs):
        mapped_distances.append(distance)
        return {
            "x": 100,
            "y": 50,
            "distance": distance * dpr,
            "source": "test",
            "located": True,
        }

    monkeypatch.setattr(solver, "_map_css_to_screen", mapping)

    def legacy_width():
        assert not bound, "Bound pointer geometry must not rescan another track"
        return track_width

    def legacy_rect():
        assert not bound, "Bound pointer geometry must not rescan another track"
        return track

    monkeypatch.setattr(solver, "_get_track_width", legacy_width)
    monkeypatch.setattr(solver, "_get_track_rect", legacy_rect)
    info = {"selector": "#handle"}
    if bound:
        info["track_rect"] = {"left": 999, "width": 999}
    endpoint = solver._do_drag_os_target(0, 0, 999, info, 0, probe)
    assert mapped_distances == [pytest.approx(158 * element_scale)]
    assert endpoint == pytest.approx(probe.point[0] + 158 * element_scale)
    assert pointer.xy[0] == pytest.approx(100 + 158 * element_scale * dpr)
    assert [event for event in pointer.events if event[0] == "button"][-1] == (
        "button",
        False,
    )
    assert not pointer.down
