"""Exact-ID ownership even when page events race with another browser user."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tools import browser_owned_page as subject
from tools import taobao_login_health as health
from tools.cdp_background_page import BackgroundPageCapacityError


def fixture(monkeypatch, *, first="owned", pages=("owned",), failure=None):
    events = []
    page_map = {
        key: SimpleNamespace(key=key, url="about:blank") for key in {first, *pages}
    }

    @contextmanager
    def expect_page(**kwargs):
        assert 0 < kwargs["timeout"] <= 5000
        events.append("expect")
        yield SimpleNamespace(value=page_map[first])
        if failure == "event":
            raise TimeoutError("event unavailable")

    class Session:
        def __init__(self, page):
            self.page = page

        def send(self, method):
            assert method == "Target.getTargetInfo"
            if failure == "metadata":
                raise RuntimeError("metadata unavailable")
            return {"targetInfo": {"targetId": self.page.key}}

        def detach(self):
            events.append("detach")

    context = SimpleNamespace(
        pages=[page_map[k] for k in pages],
        expect_page=expect_page,
        new_cdp_session=lambda p: Session(p),
        wait_for_event=lambda *a, **k: (_ for _ in ()).throw(
            TimeoutError("owned event missing")
        ),
    )

    def create(_endpoint, url):
        assert events == ["expect"] and url == "about:blank"
        events.append("create")
        if failure == "capacity":
            raise BackgroundPageCapacityError("private")
        if failure == "create":
            raise TimeoutError("missing ACK")
        return {"id": "owned"}

    monkeypatch.setattr(subject, "open_background_page", create)
    monkeypatch.setattr(
        health,
        "close_cdp_target",
        lambda _, target_id: events.append("close:" + target_id) or True,
    )
    return context, events


@pytest.mark.parametrize(
    "first,pages", [("owned", ("owned",)), ("foreign", ("foreign", "owned"))]
)
@pytest.mark.parametrize("preserve", [False, True])
def test_page_lease_binds_exact_id_and_releases_only_owned(
    monkeypatch, first, pages, preserve
):
    context, events = fixture(monkeypatch, first=first, pages=pages)
    with subject.owned_background_page(context, "http://fixture") as owned:
        assert owned.page.key == owned.target_id == "owned"
        owned.preserve = preserve
    assert events.count("create") == 1
    assert ("close:owned" in events) is not preserve
    assert "close:foreign" not in events


@pytest.mark.parametrize("failure", ["create", "capacity", "metadata", "event"])
def test_failed_attachment_does_not_guess_or_close_borrowed_id(monkeypatch, failure):
    context, events = fixture(monkeypatch, failure=failure)
    with (
        pytest.raises((RuntimeError, TimeoutError)),
        subject.owned_background_page(context, "http://fixture"),
    ):
        pytest.fail("must not yield unconfirmed page")
    assert ("close:owned" in events) == (failure in {"metadata", "event"})
    assert "close:foreign" not in events


def test_primary_failure_is_preserved_and_owned_page_released(monkeypatch):
    context, events = fixture(monkeypatch)
    with (
        pytest.raises(ValueError, match="primary"),
        subject.owned_background_page(context, "http://fixture"),
    ):
        raise ValueError("primary")
    assert events[-1] == "close:owned"


def test_stale_foreign_page_does_not_hide_acknowledged_owned_page(monkeypatch):
    from playwright.sync_api import Error

    context, events = fixture(monkeypatch, first="foreign", pages=("foreign", "owned"))
    original = context.new_cdp_session

    def session(page):
        if page.key == "foreign":
            raise Error("Target closed")
        return original(page)

    context.new_cdp_session = session
    with subject.owned_background_page(context, "http://fixture") as owned:
        assert owned.target_id == owned.page.key == "owned"
    assert events[-1] == "close:owned"


def test_missed_page_event_recovers_only_exact_acknowledged_page(monkeypatch):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    context, events = fixture(monkeypatch)

    @contextmanager
    def missed(**kwargs):
        events.append("expect")
        yield SimpleNamespace(value=None)
        raise PlaywrightTimeoutError("event missing")

    context.expect_page = missed
    with subject.owned_background_page(context, "http://fixture") as owned:
        assert owned.page.key == "owned"
    assert events[-1] == "close:owned"
