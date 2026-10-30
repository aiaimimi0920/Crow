"""Every slider probe candidate must belong to its explicit request target."""

import json

import pytest
import websocket

from tools import pc2_solver_cdp as owner

DETAIL = "https://sf-item.taobao.com/sf_item/123.htm"
SEED = "https://sf.taobao.com/list/123.htm?location_code=110100&page=4"


def tab(key, url, kind="page"):
    return {
        "id": key,
        "type": kind,
        "url": url,
        "webSocketDebuggerUrl": "ws://fixture/" + key,
    }


@pytest.fixture
def probe(monkeypatch):
    sockets = []

    class Socket:
        def __init__(self, url):
            self.key = url.rsplit("/", 1)[-1]
            self.messages = []
            self.closed = False

        def settimeout(self, timeout):
            assert 0 < timeout <= 5

        def send(self, payload):
            self.messages.append(json.loads(payload))

        def recv(self):
            message = self.messages[-1]
            return json.dumps(
                {
                    "id": message["id"],
                    "result": {"result": {"value": {"found": self.key != "empty"}}},
                }
            )

        def close(self):
            self.closed = True

    def connect(url, **kwargs):
        assert kwargs == {"suppress_origin": True, "timeout": 5}
        assert not sockets or sockets[-1].closed
        socket = Socket(url)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)

    def run(tabs, target):
        reads = []

        def fetch(url, *, timeout):
            reads.append((url, timeout))
            return tabs

        monkeypatch.setattr(owner, "fetch_json", fetch)
        result = owner.check_cdp_browser_for_slider("http://cdp", target_url=target)
        assert reads == [("http://cdp/json/list", 5)]
        assert all(socket.closed for socket in sockets)
        return result, sockets

    return run


@pytest.mark.parametrize("kind", ["page", "iframe"])
@pytest.mark.parametrize(
    "target,foreign",
    [
        (DETAIL, DETAIL.replace("123.htm", "456.htm")),
        (DETAIL, SEED),
        (SEED, SEED.replace("page=4", "page=5")),
        (SEED, SEED.replace("110100", "310100")),
        (SEED, DETAIL),
        (DETAIL, "https://example.test/unrelated"),
    ],
)
def test_foreign_inline_slider_never_triggers_targeted_probe(
    probe, kind, target, foreign
):
    result, sockets = probe(
        [tab("foreign", foreign, kind), tab("empty", target)], target
    )
    assert result is None
    assert [socket.key for socket in sockets] == ["empty"]


@pytest.mark.parametrize("kind", ["page", "iframe"])
@pytest.mark.parametrize(
    "candidate",
    [
        DETAIL,
        DETAIL + "?spm=tracking",
        DETAIL + "/_____tmd_____/punish?x5secdata=opaque",
    ],
)
def test_matching_detail_candidate_is_still_probed(probe, kind, candidate):
    result, sockets = probe([tab("matching", candidate, kind)], DETAIL)
    assert result["_target_id"] == "matching"
    assert result["_target_url"] == candidate
    assert [socket.key for socket in sockets] == ["matching"]


def test_requested_inline_page_wins_over_foreign_inline_slider(probe):
    result, sockets = probe(
        [tab("foreign", DETAIL.replace("123.htm", "456.htm")), tab("matching", DETAIL)],
        DETAIL,
    )
    assert result["_target_id"] == "matching"
    assert [socket.key for socket in sockets] == ["matching"]


def test_seed_challenge_redirect_without_query_keeps_existing_fallback(probe):
    redirected = (
        "https://sf.taobao.com/list/123.htm/_____tmd_____/punish?x5secdata=opaque"
    )
    result, sockets = probe([tab("matching", redirected)], SEED)
    assert result["_target_id"] == "matching"
    assert any(
        message["method"] == "Page.bringToFront" for message in sockets[0].messages
    )


@pytest.mark.parametrize("kind", ["page", "iframe"])
def test_unbound_probe_retains_existing_scan_behavior(probe, kind):
    result, sockets = probe(
        [tab("matching", "https://example.test/slider", kind)], None
    )
    assert result["_target_id"] == "matching"
    assert [socket.key for socket in sockets] == ["matching"]


def test_foreign_challenge_is_not_activated_or_probed(probe):
    result, sockets = probe(
        [
            tab(
                "foreign",
                DETAIL.replace("123.htm", "456.htm") + "/_____tmd_____/punish",
            )
        ],
        DETAIL,
    )
    assert result is None
    assert sockets == []


@pytest.mark.parametrize(
    "candidate,expected",
    [
        (DETAIL + "?spm=tracking", True),
        (DETAIL + "/_____tmd_____/punish?spm=tracking&x5secdata=opaque", True),
        (DETAIL.replace("123.htm", "456.htm") + "?spm=tracking", False),
        (DETAIL.replace("sf-item.taobao.com", "example.test"), False),
        ("https://login.taobao.com/", False),
    ],
)
def test_detail_matching_uses_canonical_item_without_admitting_foreign_pages(
    candidate, expected
):
    solver = owner._create_probe_solver(
        cdp_endpoint="http://fixture", target_url=DETAIL
    )
    assert (
        owner._challenge_target_matches_request(solver, DETAIL, candidate) is expected
    )


def test_plain_seed_without_identity_query_is_not_a_redirect_fallback(probe):
    result, sockets = probe([tab("foreign", SEED.split("?", 1)[0])], SEED)
    assert result is None
    assert sockets == []
