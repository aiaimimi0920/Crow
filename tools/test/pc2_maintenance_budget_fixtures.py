"""Real maintenance opening with virtual HTTP creation and a timed CDP socket."""

from types import SimpleNamespace
from unittest.mock import Mock

from src import captcha_budget, captcha_cdp
from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution as execution
from tools.test.cdp_navigation_wait_fixtures import NavigationSocket

TARGETS = {
    "seed": "https://sf.taobao.com/list/1.htm?page=2&location_code=31",
    "detail": "https://sf-item.taobao.com/sf_item/123.htm",
}
OPERATIONS = ("rotate_failed_challenge_target", "rebuild_missing_challenge_target")


def maintenance_probe(
    monkeypatch, *, delay=7.0, remaining=60.0, create_delay=0.0, on_wait=None
):
    now = [100.0]
    monkeypatch.setattr("src.captcha_cdp_command.time.monotonic", lambda: now[0])
    budget = SolveBudget(deadline=100 + remaining, clock=lambda: now[0])
    monkeypatch.setattr(captcha_budget, "SolveBudget", lambda **_kwargs: budget)
    socket = NavigationSocket(
        now,
        [(delay, {"id": 1, "result": {"frameId": "frame", "loaderId": "loader"}})],
        on_wait=on_wait,
    )
    owners, create_budgets = [], []

    class MaintenanceSolver(CaptchaSolver):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            owners.append(self)

    monkeypatch.setattr(execution, "_solver_class", lambda: MaintenanceSolver)
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: [])
    close_target = Mock(
        side_effect=AssertionError("maintenance must retain opened page")
    )
    monkeypatch.setattr(MaintenanceSolver, "_close_cdp_target", close_target)

    def create(*_args, **_kwargs):
        create_budgets.append(getattr(owners[-1], "_solve_budget", None))
        now[0] += create_delay
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "id": "fresh",
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": "ws://localhost/devtools/page/fresh",
            },
        )

    put = Mock(side_effect=create)
    monkeypatch.setattr(captcha_cdp.requests, "put", put)

    def connect(solver, *_args):
        solver.ws = socket
        return True

    monkeypatch.setattr(MaintenanceSolver, "_connect_to_target", connect)
    return SimpleNamespace(
        now=now,
        budget=budget,
        socket=socket,
        owners=owners,
        create_budgets=create_budgets,
        put=put,
        close_target=close_target,
    )
