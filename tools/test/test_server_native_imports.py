"""Control transports can load before server runtime initialization."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.test.server_native_import_cases import (
    CONTROL_IMPORT_MODULES as _CONTROL_IMPORT_MODULES,
)


@pytest.fixture(scope="module")
def control_import_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("control-import-probes")

    def probe(module_name):
        directory = root / module_name
        directory.mkdir()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib, sys; "
                    f"importlib.import_module({module_name!r}); "
                    "forbidden = {'src.server_context', 'src.server', "
                    "'src.captcha_solver', 'src.storage', 'src.avm', 'src.llm_helper', "
                    "'tools.apply_avm_calibration_patch'}; "
                    "loaded = forbidden.intersection(sys.modules); "
                    "assert not loaded, loaded"
                ),
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result

    # Every assertion still sees a fresh interpreter and private working directory.
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(
            zip(_CONTROL_IMPORT_MODULES, pool.map(probe, _CONTROL_IMPORT_MODULES))
        )


@pytest.mark.parametrize("module_name", _CONTROL_IMPORT_MODULES)
def test_control_import_does_not_initialize_server(module_name, control_import_results):
    result = control_import_results[module_name]
    assert result.returncode == 0, result.stdout + result.stderr


def test_response_handler_uses_native_serialization_dependency(monkeypatch):
    from src import server, server_http_responses

    writes = []
    monkeypatch.setattr(
        server_http_responses,
        "_write_json_response",
        lambda handler, status, payload: writes.append((handler, status, payload)),
    )
    handler = SimpleNamespace(path="/api/collection/jobs", headers={})
    payload = {"status": "queued"}
    server.DataHandler.send_json(handler, payload)

    assert writes == [(handler, 200, payload)]


_BOOTSTRAP_CASES = [
    (configured, explicit) for explicit in (False, True) for configured in (False, True)
]


@pytest.fixture(scope="module")
def bootstrap_path_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("bootstrap-path-probes")

    def probe(case):
        configured_root, explicit_paths = case
        tmp_path = root / f"{configured_root}-{explicit_paths}"
        tmp_path.mkdir()
        env = dict(os.environ)
        for key in (
            "FAPAI_SOLVER_STATE_DIR",
            "FAPAI_NAS_AUTH_RECOVERY_STATE_PATH",
            "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE",
        ):
            env.pop(key, None)
        state_root = tmp_path / "scope" if configured_root else Path("datas")
        state_path = state_root / "nas-auth-recovery.json"
        token_path = state_root / "nas-auth-recovery.token"
        if configured_root:
            env["FAPAI_SOLVER_STATE_DIR"] = str(state_root)
        if explicit_paths:
            state_path = tmp_path / "state.json"
            token_path = tmp_path / "recovery.token"
            env["FAPAI_NAS_AUTH_RECOVERY_STATE_PATH"] = str(state_path)
            env["FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE"] = str(token_path)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; from pathlib import Path; "
                    "from src import server_context, server_request_guard; "
                    "assert server_context.NAS_AUTH_RECOVERY_STATE_PATH == Path(sys.argv[1]); "
                    "assert server_context.NAS_AUTH_RECOVERY_TOKEN_FILE == Path(sys.argv[2]); "
                    "assert server_request_guard.NAS_AUTH_RECOVERY_TOKEN_FILE == Path(sys.argv[2])"
                ),
                str(state_path),
                str(token_path),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result, tmp_path, state_path, token_path

    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(_BOOTSTRAP_CASES, pool.map(probe, _BOOTSTRAP_CASES)))


@pytest.mark.parametrize("configured_root", [False, True])
@pytest.mark.parametrize("explicit_paths", [False, True])
def test_bootstrap_recovery_paths_keep_existing_precedence(
    bootstrap_path_results, configured_root, explicit_paths
):
    result, tmp_path, state_path, token_path = bootstrap_path_results[
        (configured_root, explicit_paths)
    ]
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / token_path).exists()
    assert not (tmp_path / state_path).exists()


def test_manual_review_readers_follow_replaced_runtime_dependencies(
    monkeypatch, tmp_path
):
    from src import collection_stage_status, server

    calls = []

    def snapshot(data_root, *, repository):
        calls.append((data_root, repository))
        return {"root": str(data_root)}

    monkeypatch.setattr(
        collection_stage_status, "_db_collection_stage_snapshot", snapshot
    )
    for name in ("first", "replacement"):
        repository = SimpleNamespace(name=name)
        data_root = tmp_path / name
        monkeypatch.setattr(server, "DB_REPOSITORY", repository)
        monkeypatch.setattr(server, "DATA_DIR", str(data_root))
        assert server._db_collection_stage_snapshot() == {"root": str(data_root)}
        assert calls[-1] == (data_root, repository)
    assert len(calls) == 2


def test_server_bootstrap_defers_html_parser(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from src import server_context; "
                "assert 'bs4' not in sys.modules; "
                "assert 'sqlalchemy.dialects.postgresql' not in sys.modules; "
                "assert 'sqlalchemy.dialects.sqlite' not in sys.modules; "
                "assert server_context.llm_helper.filter_content('<p>ready</p>') == 'ready'; "
                "assert 'bs4' in sys.modules"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_auth_confirmations_follow_replaced_runtime_and_path(monkeypatch, tmp_path):
    from src import server
    from src.runtime_state import RuntimeState

    states = []
    for name in ("first", "replacement"):
        runtime = RuntimeState()
        path = tmp_path / name / "confirmations.json"
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(
            server, "_auth_completion_confirmation_path", lambda path=path: path
        )
        assert server._remember_auth_completion_confirmation(name) is None
        assert server._auth_completion_was_confirmed(name) is True
        assert set(server._read_auth_completion_confirmations()) == {name}
        states.append(runtime.recovery.confirmation_snapshot())
    assert server._auth_completion_was_confirmed("first") is False
    assert set(states[0]) == {"first"}
    assert set(states[1]) == {"replacement"}


@pytest.mark.parametrize(
    "name,query,expected",
    [
        (
            "items",
            {"stage": ["unknown"], "limit": ["9999"], "offset": ["-2"]},
            {"stage": "links", "limit": 500, "offset": 0, "location_code": None},
        ),
        ("regions", {"stage": [" DETAILS "]}, {"stage": "details"}),
        (
            "item",
            {"item_id": [" item-1 "], "max_chars": ["invalid"]},
            {"item_id": "item-1", "max_chars": 100_000},
        ),
    ],
)
def test_observer_queries_use_current_repository(monkeypatch, name, query, expected):
    from src import collection_observer_queries, server

    method = {
        "items": "collection_observer_items",
        "regions": "collection_observer_regions",
        "item": "collection_observer_item_detail",
    }[name]
    facade = getattr(server, f"_collection_observer_{name}_payload")
    native = getattr(collection_observer_queries, name)
    for identity in ("first", "replacement"):
        calls = []

        def capture(*args, identity=identity, calls=calls, **kwargs):
            calls.append({**kwargs, **({"item_id": args[0]} if args else {})})
            return {"repository": identity}

        repository = SimpleNamespace(enabled=True, **{method: capture})
        monkeypatch.setattr(server, "DB_REPOSITORY", repository)
        assert facade(query)["repository"] == identity
        assert native(query, repository=repository)["repository"] == identity
        assert calls == [expected, expected]


@pytest.mark.parametrize("enabled", [False, True])
def test_observer_queries_keep_unavailable_repository_payloads(enabled):
    from src import collection_observer_queries as queries

    repository = SimpleNamespace(enabled=enabled)
    assert queries.items({}, repository=repository) == {
        "stage": "links",
        "limit": 100,
        "offset": 0,
        "location_code": None,
        "total": 0,
        "items": [],
        "db_mode": enabled,
    }
    assert queries.regions({}, repository=repository) == {
        "ok": True,
        "stage": "links",
        "regions": [],
        "db_mode": enabled,
    }
    assert queries.item({}, repository=repository) == {
        "found": False,
        "error": "item_id is required",
        "item_id": "",
    }
    assert queries.item({"item_id": ["missing"]}, repository=repository) == {
        "found": False,
        "item_id": "missing",
        "item": None,
        "occurrences": [],
        "artifacts": {},
        "db_mode": enabled,
    }


def test_lightweight_status_uses_native_builder_and_current_dependencies(monkeypatch):
    from src import collection_status_payload, server

    seen = []
    snapshots = SimpleNamespace(
        snapshot=lambda repository, loader: {
            "counts": loader(),
            "metadata": {"valid": repository.enabled},
        }
    )
    monkeypatch.setattr(server._collection_statistics, "SNAPSHOTS", snapshots)

    def build(snapshot, **dependencies):
        seen.append((snapshot, dependencies["load_runtime_snapshot"]()))
        return {
            "db_mode": dependencies["database_enabled"](),
            "metrics": dependencies["load_api_metrics"](),
        }

    monkeypatch.setattr(collection_status_payload, "build_lightweight_status", build)
    for enabled in (False, True):
        monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=enabled))
        monkeypatch.setattr(
            server, "_load_collection_seed_queue_counts", lambda: {"count": 3}
        )
        monkeypatch.setattr(
            server,
            "_collection_runtime_snapshot",
            lambda enabled=enabled: {"paused": enabled},
        )
        monkeypatch.setattr(
            server, "llm_helper", SimpleNamespace(get_api_metrics=lambda: {"calls": 8})
        )
        assert server._collection_api_lightweight_status_payload() == {
            "db_mode": enabled,
            "metrics": {"calls": 8},
        }
        assert seen[-1] == (
            {"counts": {"count": 3}, "metadata": {"valid": enabled}},
            {"paused": enabled},
        )


@pytest.mark.parametrize("mode", ["disabled", "missing", "native", "legacy", "error"])
@pytest.mark.parametrize("entrypoint", ["facade", "native"])
def test_queue_count_loading_preserves_repository_contract(
    monkeypatch, mode, entrypoint
):
    from src import collection_queue_counts, server

    calls = []

    def native():
        calls.append("native")
        if mode == "error":
            raise RuntimeError("count read failed")
        return {"seed_item_raw_detail_captured": 6, "extension_count": 9}

    def legacy():
        calls.append("legacy")
        return {
            "search_pending": "2",
            "search_in_progress": None,
            "search_done": 3,
            "search_pruned": 4,
        }

    repository = SimpleNamespace(enabled=mode != "disabled")
    if mode in ("disabled", "native", "error"):
        repository.seed_queue_counts = native
    if mode != "missing":
        repository.search_task_counts = legacy
    monkeypatch.setattr(server, "DB_REPOSITORY", repository)
    load = (
        server._load_collection_seed_queue_counts
        if entrypoint == "facade"
        else lambda: collection_queue_counts.load_counts(repository)
    )
    if mode == "error":
        with pytest.raises(RuntimeError, match="count read failed"):
            load()
        assert calls == ["native"]
        return
    result = load()
    assert result["seed_item_detail_completed"] == 0
    if mode == "native":
        assert calls == ["native"]
        assert result["seed_item_raw_detail_captured"] == 6
        assert result["extension_count"] == 9
    elif mode == "legacy":
        assert calls == ["legacy"]
        assert [
            result["seed_scan_job_" + status]
            for status in ("pending", "in_progress", "completed", "blocked")
        ] == [2, 0, 3, 4]
    else:
        assert calls == []
        assert set(result.values()) == {0}
    result["seed_item_detail_completed"] = 99
    assert server._empty_seed_queue_counts()["seed_item_detail_completed"] == 0


@pytest.mark.parametrize(
    "reason, expected", [(None, True), ("operator", True), ("manual_required", False)]
)
@pytest.mark.parametrize("failure", [None, "restart", "challenge", "watcher"])
def test_overview_delegates_after_runtime_and_diagnostic_reads(
    monkeypatch, tmp_path, reason, expected, failure
):
    from src import collection_status_payload, server
    from src.runtime_state import RuntimeState

    runtime = RuntimeState()
    runtime.control.set_pause(True, reason)
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=tmp_path))
    status = {"collection_stage": {"seed_queue": {"seed_occurrence_total": 7}}}
    monkeypatch.setattr(
        server, "_collection_api_lightweight_status_payload", lambda: status
    )
    calls = []
    error = OSError("diagnostic unavailable")

    def diagnostic(name, path=None):
        if path is not None:
            assert path == tmp_path
        calls.append(name)
        if name == failure:
            raise error
        return {"source": name}

    def modules(current, counts):
        calls.append("modules")
        assert current is status
        assert current["operator_paused"] is expected
        assert counts == {"seed_occurrence_total": 7}
        return {"native": True}

    monkeypatch.setattr(server, "_engine_restart_status", lambda: diagnostic("restart"))
    monkeypatch.setattr(
        server,
        "_hybrid_collection_challenge_metrics_summary",
        lambda path: diagnostic("challenge", path),
    )
    monkeypatch.setattr(
        server,
        "_pc1_auth_auto_resume_state_summary",
        lambda path: diagnostic("watcher", path),
    )
    monkeypatch.setattr(collection_status_payload, "build_overview_modules", modules)
    if failure:
        with pytest.raises(OSError) as caught:
            server._collection_observer_overview_payload()
        assert caught.value is error
        order = ["restart", "challenge", "watcher"]
        assert calls == order[: order.index(failure) + 1]
        return
    result = server._collection_observer_overview_payload()
    assert result["modules"] == {"native": True}
    assert calls == ["restart", "challenge", "watcher", "modules"]


@pytest.mark.parametrize("scopes", [{"seed": {"paused": True}}, None, [], "invalid"])
@pytest.mark.parametrize("failure", [None, "solver", "recovery"])
@pytest.mark.parametrize("entrypoint", ["native", "facade"])
def test_runtime_snapshot_reads_once_in_order(monkeypatch, scopes, failure, entrypoint):
    from src import collection_status_payload, server

    calls = []
    solver = {"paused": 1, "collection_scopes": scopes}
    recovery = {"state": "idle"}
    error = RuntimeError("snapshot unavailable")

    def read(name, value):
        calls.append(name)
        if failure == name:
            raise error
        return value

    monkeypatch.setattr(
        server, "_captcha_solver_runtime_status", lambda: read("solver", solver)
    )
    monkeypatch.setattr(
        server,
        "NAS_AUTH_RECOVERY",
        SimpleNamespace(snapshot=lambda: read("recovery", recovery)),
    )

    def snapshot():
        if entrypoint == "facade":
            return server._collection_runtime_snapshot()
        return collection_status_payload.build_runtime_snapshot(
            load_solver_status=lambda: read("solver", solver),
            load_auth_recovery=lambda: read("recovery", recovery),
        )

    if failure:
        with pytest.raises(RuntimeError) as caught:
            snapshot()
        assert caught.value is error
    else:
        result = snapshot()
        assert result["paused"] is True
        assert result["captcha_solver"] is solver
        assert result["auth_recovery"] is recovery
        if isinstance(scopes, dict):
            assert result["collection_scopes"] is scopes
        else:
            assert result["collection_scopes"] == {}
    assert calls == (["solver"] if failure == "solver" else ["solver", "recovery"])
