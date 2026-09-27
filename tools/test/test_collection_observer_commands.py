"""Observer writes validate requests and use only the injected repository."""

from types import SimpleNamespace

import pytest

from src import collection_observer_commands as commands

CASES = [
    (
        "reanalysis",
        "requeue_seed_detail_analysis",
        {"item_id": " item-1 ", "reason": " "},
        ("item-1",),
        {"reason": "operator_requested"},
    ),
    (
        "manual_update",
        "manual_update_flat_item",
        {"item_id": " item-1 ", "updates": {"title": "updated"}},
        ("item-1", {"title": "updated"}),
        {},
    ),
    (
        "reset_region_links",
        "reset_seed_link_region",
        {"location_code": " 440115 "},
        ("440115",),
        {},
    ),
]


@pytest.fixture(params=["native", "facade"])
def invoke(request, monkeypatch):
    def call(name, payload, repository):
        if request.param == "native":
            return getattr(commands, name)(payload, repository=repository)
        from src import server

        monkeypatch.setattr(server, "DB_REPOSITORY", repository)
        return getattr(server, f"_collection_observer_{name}_payload")(payload)

    return call


@pytest.mark.parametrize("name,method,payload,args,kwargs", CASES)
def test_commands_follow_repository_replacement(
    invoke, name, method, payload, args, kwargs
):
    for identity in ("first", "replacement"):
        calls = []

        def mutate(*actual_args, calls=calls, identity=identity, **actual_kwargs):
            calls.append((actual_args, actual_kwargs))
            return {"ok": True, "repository": identity}

        repository = SimpleNamespace(enabled=True, **{method: mutate})
        assert invoke(name, payload, repository) == {
            "ok": True,
            "repository": identity,
            "db_mode": True,
        }
        assert calls == [(args, kwargs)]


@pytest.mark.parametrize("name,method,payload,args,kwargs", CASES)
@pytest.mark.parametrize("enabled", [False, True])
def test_commands_reject_unavailable_repository(
    invoke, name, method, payload, args, kwargs, enabled
):
    result = invoke(name, payload, SimpleNamespace(enabled=enabled))
    assert result["ok"] is False
    assert result["db_mode"] is enabled
    assert result["error"] == "database repository is not available"


@pytest.mark.parametrize(
    "name,payload",
    [
        ("reanalysis", {}),
        ("manual_update", {}),
        ("reset_region_links", {}),
        ("manual_update", {"item_id": "item-1", "updates": {}}),
        ("manual_update", {"item_id": "item-1", "updates": []}),
    ],
)
def test_invalid_command_never_accesses_repository(invoke, name, payload):
    class UnavailableRepository:
        @property
        def enabled(self):
            raise AssertionError("repository accessed before request validation")

    assert invoke(name, payload, UnavailableRepository())["ok"] is False


@pytest.mark.parametrize("name,method,payload,args,kwargs", CASES)
def test_repository_failure_reaches_http_error_boundary(
    invoke, name, method, payload, args, kwargs
):
    def fail(*_args, **_kwargs):
        raise OSError("publication rejected")

    repository = SimpleNamespace(enabled=True, **{method: fail})
    with pytest.raises(OSError, match="publication rejected"):
        invoke(name, payload, repository)
