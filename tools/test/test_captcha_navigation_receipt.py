"""Document correlation is bounded evidence, never authorization for input/auth."""

import json
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_navigation_receipt import NavigationReceipt, navigation_binding_fields
from src.captcha_solver import CaptchaSolver
from tools.test.test_captcha_target_open_recovery import stopping_budget

TARGET = "https://sf.taobao.com/list/all.htm?page=2&st_param=PRIVATE_MARKER"
CHALLENGE = (
    "https://sf.taobao.com/list/all.htm/_____tmd_____/verify?x5secdata=PRIVATE_MARKER"
)


def receipt_solver():
    solver = CaptchaSolver(target_url=TARGET)
    solver.target_id = "PRIVATE_TARGET"
    solver._opened_target_ids.add(solver.target_id)
    solver._navigation_receipt = NavigationReceipt(
        solver.target_id,
        solver._normalize_target_url(TARGET),
        "PRIVATE_FRAME",
        "PRIVATE_LOADER",
    )
    solver._send_cdp = Mock(return_value=frame_tree())
    return solver


def frame_tree(**extra):
    return {
        "frameTree": {
            "frame": {
                "id": "PRIVATE_FRAME",
                "loaderId": "PRIVATE_LOADER",
                "url": CHALLENGE,
                **extra,
            }
        }
    }


def test_receipt_compares_fresh_root_document_without_authorizing_missing_identity():
    from src.captcha_verification import ready_target_matches

    solver = receipt_solver()
    summary = {"href": CHALLENGE, "readyState": "complete", "hasSlider": True}
    result = navigation_binding_fields(solver, summary)
    assert result == {
        "navigation_probe": "ok",
        "navigation_frame": "match",
        "navigation_loader": "match",
        "navigation_url": "match",
    }
    assert not ready_target_matches(summary, TARGET)
    assert "PRIVATE" not in json.dumps(result) + repr(solver._navigation_receipt)
    solver._send_cdp.assert_called_once_with("Page.getFrameTree")


@pytest.mark.parametrize(
    ("extra", "key", "expected"),
    [
        ({"id": "other"}, "navigation_frame", "different"),
        ({"id": None}, "navigation_frame", "missing"),
        ({"loaderId": "other"}, "navigation_loader", "different"),
        ({"loaderId": ""}, "navigation_loader", "missing"),
        ({"url": TARGET}, "navigation_url", "different"),
        ({"url": "https://evil.invalid/PRIVATE"}, "navigation_url", "invalid"),
        ({"url": []}, "navigation_url", "invalid"),
    ],
)
def test_root_frame_relations_are_fixed_enums(extra, key, expected):
    solver = receipt_solver()
    solver._send_cdp.return_value = frame_tree(**extra)
    assert navigation_binding_fields(solver, {"href": CHALLENGE})[key] == expected


@pytest.mark.parametrize(
    ("root", "observed", "expected"),
    [
        (TARGET, TARGET.replace("page=2&st_param=", "st_param=") + "&page=2", "match"),
        (TARGET + "&page=2", TARGET, "different"),
        (
            "https://sf-item.taobao.com/sf_item/123.htm",
            "https://susong-item.taobao.com/auction/123.htm/_____tmd_____/verify",
            "match",
        ),
    ],
)
def test_url_comparison_preserves_existing_identity_semantics(root, observed, expected):
    solver = receipt_solver()
    solver._send_cdp.return_value = frame_tree(url=root)
    assert (
        navigation_binding_fields(solver, {"href": observed})["navigation_url"]
        == expected
    )


def test_same_document_ack_does_not_invent_loader_evidence():
    solver = receipt_solver()
    old = solver._navigation_receipt
    solver._navigation_receipt = NavigationReceipt(
        old.target_id, old.target_url, old.frame_id, None
    )
    assert (
        navigation_binding_fields(solver, {"href": CHALLENGE})["navigation_loader"]
        == "missing"
    )


@pytest.mark.parametrize(
    "tree",
    [
        None,
        {},
        [],
        {"frameTree": []},
        {"frameTree": {"frame": []}},
        frame_tree(parentId="parent"),
    ],
)
def test_malformed_or_child_frame_never_becomes_document_evidence(tree):
    solver = receipt_solver()
    solver._send_cdp.return_value = tree
    assert set(navigation_binding_fields(solver, {}).values()) == {"unavailable"}


@pytest.mark.parametrize(
    "change", ["target", "owner", "request", "invalid_request", "receipt"]
)
def test_changed_request_or_target_does_not_read_a_frame(change):
    solver = receipt_solver()
    if change == "target":
        solver.target_id = "other"
    elif change == "owner":
        solver._opened_target_ids.clear()
    elif change == "request":
        solver.target_url = TARGET + "&page=3"
    elif change == "invalid_request":
        solver.target_url = "https://sf.taobao.com:invalid/list/all.htm"
    else:
        solver._navigation_receipt = None
    result = navigation_binding_fields(solver, {})
    assert (
        result == {}
        if change == "receipt"
        else result["navigation_probe"] == "target_changed"
    )
    solver._send_cdp.assert_not_called()


@pytest.mark.parametrize("change", ["target", "receipt"])
def test_target_changed_during_read_does_not_report_old_document(change):
    solver = receipt_solver()

    def read(*_):
        if change == "target":
            solver.target_id = "other"
        else:
            solver._navigation_receipt = None
        return frame_tree()

    solver._send_cdp.side_effect = read
    assert navigation_binding_fields(solver, {})["navigation_probe"] == "target_changed"


def test_three_read_limit_never_reuses_a_snapshot():
    solver = receipt_solver()
    for _ in range(3):
        assert (
            navigation_binding_fields(solver, {"href": CHALLENGE})["navigation_probe"]
            == "ok"
        )
    result = navigation_binding_fields(solver, {})
    assert result == {
        "navigation_probe": "limited",
        "navigation_frame": "not_read",
        "navigation_loader": "not_read",
        "navigation_url": "not_read",
    }
    assert solver._send_cdp.call_count == 3


@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
@pytest.mark.parametrize("when", ["before", "during", "limited"])
def test_cancel_and_deadline_remain_prioritized(stop, when):
    solver = receipt_solver()
    trigger = stopping_budget(solver, stop)
    if when == "during":
        solver._send_cdp.side_effect = lambda *_: trigger() or frame_tree()
    else:
        solver._navigation_binding_reads = 3 if when == "limited" else 0
        trigger()
    with pytest.raises(SolveStopped):
        navigation_binding_fields(solver, {})
    assert solver.last_failure_reason == (
        "deadline_exceeded" if stop == "deadline" else "cancelled"
    )
    assert solver._send_cdp.call_count == (1 if when == "during" else 0)


def test_unavailable_read_is_non_authorizing_and_does_not_log_exception(caplog):
    solver = receipt_solver()
    solver._send_cdp.side_effect = OSError("PRIVATE_MARKER")
    assert set(navigation_binding_fields(solver, {}).values()) == {"unavailable"}
    assert "PRIVATE_MARKER" not in caplog.text


def test_solve_stopped_is_not_hidden_by_diagnostics():
    solver = receipt_solver()
    solver._send_cdp.side_effect = SolveStopped("cancelled")
    with pytest.raises(SolveStopped):
        navigation_binding_fields(solver, {})


@pytest.mark.parametrize("operation", ["switch", "reset"])
def test_receipt_is_invalidated_on_target_lifecycle(operation):
    solver = receipt_solver()
    if operation == "switch":
        solver._remember_target_tab({"id": "other", "url": TARGET})
    else:
        solver._reset_current_target()
    assert solver._navigation_receipt is None
    assert navigation_binding_fields(solver, {}) == {}
    solver._send_cdp.assert_not_called()


def test_new_navigation_attempt_clears_previous_receipt_even_if_attachment_fails():
    solver = receipt_solver()
    solver._navigation_binding_reads = 2
    solver._connect_to_target = Mock(return_value=False)
    assert not solver._prepare_opened_target_before_navigation(
        {"id": solver.target_id, "webSocketDebuggerUrl": "ws://local"}, TARGET
    )
    assert solver._navigation_receipt is None and solver._navigation_binding_reads == 0
    solver._send_cdp.assert_not_called()
