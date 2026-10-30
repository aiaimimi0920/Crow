"""Mixed CDP event/ACK fixtures; no browser, socket or upstream access."""

import json
from unittest.mock import Mock

from src.captcha_solver import CaptchaSolver

TARGET = "https://sf.taobao.com/list/all.htm?page=2&st_param=PRIVATE_MARKER"
CHALLENGE = (
    "https://sf.taobao.com/list/all.htm/_____tmd_____/verify?x5secdata=PRIVATE_MARKER"
)
FRAME, FIRST, NEXT = "PRIVATE_FRAME", "PRIVATE_LOADER_1", "PRIVATE_LOADER_2"


def event(method, **params):
    return {"method": method, "params": params}


def request(url=TARGET, *, loader=FIRST, request_id="PRIVATE_REQUEST_1", **extra):
    return event(
        "Network.requestWillBeSent",
        frameId=FRAME,
        loaderId=loader,
        requestId=request_id,
        type="Document",
        request={"url": url},
        **extra,
    )


def commit(url=CHALLENGE, *, loader=FIRST):
    return event(
        "Page.frameNavigated", frame={"id": FRAME, "loaderId": loader, "url": url}
    )


def direct():
    return [
        request(),
        request(CHALLENGE, redirectResponse={"url": TARGET, "status": 302}),
        commit(),
    ]


def scripted(reason="scriptInitiated"):
    return [
        request(),
        commit(TARGET),
        event(
            "Page.frameRequestedNavigation", frameId=FRAME, url=CHALLENGE, reason=reason
        ),
        request(CHALLENGE, loader=NEXT, request_id="PRIVATE_REQUEST_2"),
        commit(loader=NEXT),
    ]


class Socket:
    connected = True

    def __init__(self, events, *, loader=FIRST, setup_failure=None):
        self.messages, self.queue = [], []
        self.events, self.loader, self.setup_failure = events, loader, setup_failure
        self.timeout = 5

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value

    def send(self, raw):
        msg = json.loads(raw)
        self.messages.append(msg)
        method = msg["method"]
        result = {}
        if method == "Page.navigate":
            self.queue.extend(self.events)
            result = {"frameId": FRAME, "loaderId": FIRST}
        elif method == "Page.getFrameTree":
            result = {
                "frameTree": {
                    "frame": {"id": FRAME, "loaderId": self.loader, "url": CHALLENGE}
                }
            }
        if method == self.setup_failure:
            self.queue.append(
                {
                    "id": msg["id"],
                    "error": {"code": -1, "message": "fixture unavailable"},
                }
            )
        else:
            self.queue.append({"id": msg["id"], "result": result})

    def recv(self):
        return json.dumps(self.queue.pop(0))

    def close(self):
        self.connected = False


def prepared(
    events,
    *,
    loader=FIRST,
    setup_failure=None,
    target=TARGET,
    owned=True,
    before_prepare=None,
):
    solver = CaptchaSolver(target_url=target)
    payload = {
        "id": "PRIVATE_TARGET",
        "webSocketDebuggerUrl": "ws://localhost/page/fixture",
    }
    solver._remember_target_tab(payload)
    if owned:
        solver._opened_target_ids.add(payload["id"])
    sock = Socket(events, loader=loader, setup_failure=setup_failure)
    solver.ws = sock
    solver._connect_to_target = Mock(return_value=True)
    if before_prepare:
        before_prepare(solver, sock, payload)
    assert solver._prepare_opened_target_before_navigation(payload, target)
    return solver, sock
