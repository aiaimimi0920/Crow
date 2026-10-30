"""Optional description enrichment must not stall an already captured detail."""

import json
import sys
import time

import pytest

from src import llm_helper
from tools import detail_browser_capture as process_boundary
from tools.live_smoke_summary import build_description_audit
from tools.test.test_detail_capture_deadline import CHILD, alive

HTML = '<script id="description-data" type="application/json">{"link":"https://description.invalid/detail"}</script>'


def test_description_audit_uses_owned_process_and_preserves_successful_evidence(
    monkeypatch, tmp_path
):
    calls = []

    def unbounded(*args, **kwargs):
        pytest.fail("description enrichment ran without a process deadline")

    def run(command, request, *, timeout_seconds):
        calls.append((command, json.loads(request), timeout_seconds))
        return json.dumps({"text": "建筑面积88.88平方米"}).encode()

    monkeypatch.setattr(llm_helper, "fetch_description_data_text", unbounded)
    monkeypatch.setattr(process_boundary, "run_capture_process", run)
    audit = build_description_audit(HTML, tmp_path)
    assert len(calls) == 1
    command, request, timeout = calls[0]
    assert command[-1] == "tools.description_capture"
    assert request == {"html": HTML, "timeout": 20.0}
    assert timeout == 20
    assert audit["area_sqm"] == 88.88
    assert audit["has_area_marker"] is True
    assert (tmp_path / "description-data.txt").read_text(
        encoding="utf-8"
    ) == "建筑面积88.88平方米"


def test_description_timeout_keeps_optional_evidence_unknown_without_private_logs(
    monkeypatch, tmp_path, caplog
):
    calls = []

    def run(*args, **kwargs):
        calls.append(True)
        raise TimeoutError("SECRET_URL_AND_TOKEN")

    monkeypatch.setattr(llm_helper, "fetch_description_data_text", lambda *_: None)
    monkeypatch.setattr(process_boundary, "run_capture_process", run)
    assert build_description_audit(HTML, tmp_path) == {
        "area_sqm": None,
        "text_len": 0,
        "has_area_marker": False,
        "text_path": None,
    }
    assert calls == [True]
    assert "SECRET_URL_AND_TOKEN" not in caplog.text
    assert not (tmp_path / "description-data.txt").exists()


@pytest.mark.parametrize(
    "html",
    ["", "<html></html>", '<script id="description-data">invalid</script>'],
)
def test_no_valid_description_link_does_not_start_a_helper(monkeypatch, html):
    from tools.description_capture import fetch_description_with_deadline

    monkeypatch.setattr(
        process_boundary,
        "run_capture_process",
        lambda *a, **kw: pytest.fail("missing optional description started a helper"),
    )
    assert fetch_description_with_deadline(html) is None


@pytest.mark.parametrize("reply", [b"[]", b"{}", b'{"text":1}', b"SECRET_REPLY"])
def test_invalid_private_reply_is_unknown_not_business_text(monkeypatch, reply, caplog):
    from tools.description_capture import fetch_description_with_deadline

    monkeypatch.setattr(process_boundary, "run_capture_process", lambda *a, **kw: reply)
    assert fetch_description_with_deadline(HTML) is None
    assert "SECRET_REPLY" not in caplog.text


@pytest.mark.parametrize("text", [None, "", "建筑面积88.88平方米"])
def test_private_child_keeps_legacy_timeout_and_decoded_text(text, capsys):
    from tools.description_capture import description_reply

    def fetch(html, *, timeout):
        assert html == HTML and timeout == 20
        print("PRIVATE_FETCH_DIAGNOSTIC")
        return text

    assert description_reply(fetch, {"html": HTML, "timeout": 20}) == {"text": text}
    captured = capsys.readouterr()
    assert not captured.out
    assert "PRIVATE_FETCH_DIAGNOSTIC" in captured.err


@pytest.mark.parametrize(
    "error", [KeyboardInterrupt(), SystemExit("cleanup incomplete")]
)
def test_cancellation_or_unconfirmed_cleanup_is_not_silently_accepted(
    monkeypatch, error
):
    from tools.description_capture import fetch_description_with_deadline

    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(process_boundary, "run_capture_process", run)
    with pytest.raises(type(error)) as raised:
        fetch_description_with_deadline(HTML)
    assert raised.value is error


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), "bad"])
def test_invalid_deadline_does_not_launch_a_helper(monkeypatch, timeout):
    from tools.description_capture import fetch_description_with_deadline

    monkeypatch.setattr(
        process_boundary,
        "run_capture_process",
        lambda *a, **kw: pytest.fail("invalid deadline launched a process"),
    )
    with pytest.raises(ValueError):
        fetch_description_with_deadline(HTML, timeout=timeout)


def test_real_private_child_entry_does_not_need_a_network_or_model():
    request = json.dumps({"html": "<html>固定回归</html>", "timeout": 1}).encode()
    output = process_boundary.run_capture_process(
        [sys.executable, "-B", "-m", "tools.description_capture"],
        request,
        timeout_seconds=5,
    )
    assert json.loads(output) == {"text": None}


def test_synthetic_blocked_description_process_tree_is_reclaimed(monkeypatch, tmp_path):
    from tools.description_capture import fetch_description_with_deadline

    real_run = process_boundary.run_capture_process
    receipt = tmp_path / "description-processes.json"

    def run(_command, request, *, timeout_seconds):
        value = {**json.loads(request), "receipt": str(receipt), "mode": "body"}
        return real_run(
            [sys.executable, "-B", "-c", CHILD],
            json.dumps(value).encode(),
            timeout_seconds=timeout_seconds,
        )

    monkeypatch.setattr(process_boundary, "run_capture_process", run)
    started = time.monotonic()
    assert fetch_description_with_deadline(HTML, timeout=1) is None
    assert time.monotonic() - started < 7
    assert receipt.exists(), "The synthetic blocked API must actually have started"
    owned = json.loads(receipt.read_text())
    until = time.monotonic() + 2
    while any(alive(pid) for pid in owned.values()) and time.monotonic() < until:
        time.sleep(0.05)
    assert not any(alive(pid) for pid in owned.values())


def test_optional_timeout_keeps_raw_html_and_does_not_call_model(monkeypatch, tmp_path):
    from tools import live_batch_smoke as smoke

    seed = {"id": "raw-1001", "url": "https://sf-item.taobao.com/sf_item/raw-1001.htm"}
    monkeypatch.setattr(
        smoke,
        "fetch_detail_html",
        lambda *a, **kw: (HTML, seed["url"], len(HTML.encode()), "http_cookie"),
    )
    monkeypatch.setattr(smoke, "resolve_runtime_user_agent", lambda _: "fixture")
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *a, **kw: pytest.fail("raw capture called a model"),
    )

    def expired(*args, **kwargs):
        raise TimeoutError("PRIVATE_DESCRIPTION_URL")

    monkeypatch.setattr(process_boundary, "run_capture_process", expired)
    selected = smoke.process_item(
        object(),
        seed,
        {},
        config=smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://fixture",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            raw_only=True,
        ),
    )
    item_dir = tmp_path / seed["id"]
    assert (item_dir / "detail.html").read_text(encoding="utf-8") == HTML
    assert selected["detail_capture_mode"] == "raw"
    assert selected["description_data"]["area_sqm"] is None
    assert selected["description_data"]["text_path"] is None
    assert (item_dir / "selected.json").is_file()
