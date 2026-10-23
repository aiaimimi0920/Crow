import hashlib
import json
import subprocess
from copy import deepcopy

import pytest

from tools.pc2_container_inventory import canonical_containers
from tools.pc2_docker_api import clone_payload
from tools.pc2_settings_model import inventory
from tools.pc2_settings_runtime import SettingsRuntime
from tools.test.collection_settings_fixtures import FakeDocker


class ExactDocker(FakeDocker):
    def __init__(self, *, fail=None):
        super().__init__()
        self.api_calls = []
        self.fail = fail
        self.created = 0
        self.rows = {row["Id"]: row for row in self.rows.values()}
        for row in self.rows.values():
            row.update(
                HostConfig={
                    "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
                    "Binds": ["/fixture/data:/data/output:rw"],
                    "ReadonlyRootfs": True,
                },
                NetworkSettings={
                    "Networks": {
                        "fixture": {
                            "Aliases": ["worker", row["Id"][:12]],
                            "IPAddress": "172.18.0.10",
                            "NetworkID": "allocated",
                        }
                    }
                },
            )
            row["State"]["Status"] = "running"
        backup = deepcopy(next(iter(self.rows.values())))
        backup.update(Id="b" * 64, Name=backup["Name"] + "-retained")
        backup["State"] = {"Status": "exited", "Running": False}
        self.rows[backup["Id"]] = backup
        self.original = deepcopy(self.rows)

    def inspect(self, identifier):
        return deepcopy(self.rows[identifier])

    def create(self, name, payload):
        self._call("create", name)
        self.created += 1
        identifier = hashlib.sha256((name + str(self.created)).encode()).hexdigest()
        config = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in {"HostConfig", "NetworkingConfig"}
        }
        self.rows[identifier] = {
            "Id": identifier,
            "Name": "/" + name,
            "Image": payload["Image"],
            "Config": config,
            "HostConfig": deepcopy(payload["HostConfig"]),
            "State": {"Status": "created", "Running": False},
            "Mounts": deepcopy(next(iter(self.original.values()))["Mounts"]),
            "NetworkSettings": {"Networks": {}},
        }
        return identifier

    def _call(self, action, identifier):
        self.api_calls.append((action, identifier))
        if self.fail == action:
            self.fail = None
            raise RuntimeError("Synthetic Docker failure")

    def action(self, identifier, action, body=None, **query):
        self._call(action, identifier)
        row = self.rows[identifier]
        if action == "update":
            row["HostConfig"]["RestartPolicy"] = deepcopy(body["RestartPolicy"])
        elif action == "rename":
            assert not any(
                other["Name"] == "/" + query["name"] and other["Id"] != identifier
                for other in self.rows.values()
            )
            row["Name"] = "/" + query["name"]
        elif action == "stop":
            row["State"] = {"Status": "exited", "Running": False}
        elif action == "start":
            row["State"] = {
                "Status": "running",
                "Running": True,
                "Health": {"Status": "healthy"},
            }
        else:
            raise AssertionError(action)


def setup_runtime(tmp_path, docker):
    runtime = SettingsRuntime(
        tmp_path,
        [],
        runner=docker,
        docker_api=docker,
        clock=lambda: docker.time,
        sleep=docker.sleep,
    )
    previous = inventory(docker.model)["effective"]
    config = deepcopy(previous)
    config["ai"].update(model="gpt-6.1-sol", allow_gpt=True, reasoning_effort="low")
    return runtime, {
        "request_id": "settings-gpt-enable-0001",
        "previous": previous,
        "config": config,
        "api_key": None,
    }


def test_exact_ai_enable_disable_preserves_backups_and_unrelated_workers(tmp_path):
    docker = ExactDocker()
    runtime, request = setup_runtime(tmp_path, docker)
    assert runtime.apply(request) == "applied"
    assert runtime.snapshot()["effective"] == request["config"]
    rows = canonical_containers(list(docker.rows.values()))
    for name, row in rows.items():
        if name.startswith("pc2-analysis-"):
            assert row["Id"] not in docker.original
            assert row["HostConfig"]["ReadonlyRootfs"]
            assert row["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
            old = next(
                r for r in docker.original.values() if r["Name"] == "/fapaifang-" + name
            )
            assert not docker.rows[old["Id"]]["State"]["Running"]
            assert docker.rows[old["Id"]]["HostConfig"]["RestartPolicy"]["Name"] == "no"
        else:
            assert row == docker.original[row["Id"]]
    assert docker.rows["b" * 64] == docker.original["b" * 64]
    assert not any("compose" in call and "up" in call for call in docker.calls)
    disable = {
        "request_id": "settings-gpt-disable-0002",
        "previous": request["config"],
        "config": request["previous"],
        "api_key": None,
    }
    assert runtime.apply(disable) == "applied"
    assert runtime.snapshot()["effective"] == request["previous"]
    assert all(action not in {"rm", "delete"} for action, _ in docker.api_calls)


@pytest.mark.parametrize(
    "failure", ["create", "update", "stop", "rename", "start", "readiness"]
)
def test_ai_replacement_failures_roll_back_without_deleting(tmp_path, failure):
    docker = ExactDocker(fail=None if failure == "readiness" else failure)
    runtime, request = setup_runtime(tmp_path, docker)
    if failure == "readiness":
        runtime.wait_ready = lambda model: (
            model["services"]["pc2-analysis-1"]["environment"]["OPENAI_MODEL"]
            == "deepseek-fixture"
        )
    assert runtime.apply(request) == "rolled_back"
    assert runtime.snapshot()["effective"] == request["previous"]
    for row in runtime.inspect().values():
        old = docker.original[row["Id"]]
        assert row["Name"] == old["Name"]
        assert row["Config"] == old["Config"]
        assert row["HostConfig"] == old["HostConfig"]
        assert row["State"]["Running"]


def test_non_ai_change_still_rejects_service_wide_compose_with_backups(tmp_path):
    docker = ExactDocker()
    # Retained analysis backup sharing the target labels.
    backup = deepcopy(
        next(row for row in docker.rows.values() if "analysis-1" in row["Name"])
    )
    backup.update(Id="c" * 64, Name=backup["Name"] + "-retained")
    backup["State"] = {"Status": "exited", "Running": False}
    docker.rows[backup["Id"]] = backup
    runtime, request = setup_runtime(tmp_path, docker)
    request["config"]["intervals"]["analysis"] = 17
    assert runtime.apply(request) == "rejected"
    assert not docker.api_calls


def test_preflight_identity_drift_never_stops_a_worker(tmp_path):
    docker = ExactDocker()
    runtime, request = setup_runtime(tmp_path, docker)
    original = docker.inspect

    def drift(identifier):
        row = original(identifier)
        row["HostConfig"]["ReadonlyRootfs"] = False
        return row

    docker.inspect = drift
    assert runtime.apply(request) == "rolled_back"
    assert not docker.api_calls


@pytest.mark.parametrize("changed_source", [False, True])
def test_mount_enumeration_order_is_not_drift_but_mount_content_is(
    tmp_path, changed_source
):
    docker = ExactDocker()
    for service in docker.model["services"].values():
        if "volumes" in service:
            service["volumes"].append(
                {"type": "bind", "source": "/fixture/second", "target": "/data/second"}
            )
    for row in docker.rows.values():
        row["Mounts"].append(
            {
                "Type": "bind",
                "Source": "/fixture/second",
                "Destination": "/data/second",
                "RW": True,
            }
        )
    docker.original = deepcopy(docker.rows)
    original = docker.inspect

    def inspect(identifier):
        row = original(identifier)
        row["Mounts"].reverse()
        if changed_source:
            row["Mounts"][0]["Source"] = "/unexpected"
        return row

    docker.inspect = inspect
    runtime, request = setup_runtime(tmp_path, docker)
    assert runtime.apply(request) == ("rolled_back" if changed_source else "applied")
    if changed_source:
        assert not docker.api_calls


def test_clone_retains_security_and_user_network_configuration_only():
    docker = ExactDocker()
    row = next(iter(docker.rows.values()))
    row["NetworkSettings"]["Networks"]["fixture"]["IPAMConfig"] = {
        "IPv4Address": "172.18.0.9"
    }
    payload = clone_payload(row, {"KEY": "synthetic-$value"})
    endpoint = payload["NetworkingConfig"]["EndpointsConfig"]["fixture"]
    assert endpoint == {
        "IPAMConfig": {"IPv4Address": "172.18.0.9"},
        "Aliases": ["worker"],
    }
    assert payload["Env"] == ["KEY=synthetic-$value"]
    assert payload["HostConfig"]["ReadonlyRootfs"]
    assert "allocated" not in json.dumps(payload)
    row["HostConfig"]["AutoRemove"] = True
    with pytest.raises(ValueError):
        clone_payload(row, {})


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "docker"),
        subprocess.TimeoutExpired("docker", 1),
    ],
)
@pytest.mark.parametrize("rollback_failure", [False, True])
def test_readiness_transport_error_rolls_back_or_reports_interrupted(
    tmp_path, error, rollback_failure
):
    docker = ExactDocker()
    runtime, request = setup_runtime(tmp_path, docker)

    def ready(model):
        if (
            rollback_failure
            or model["services"]["pc2-analysis-1"]["environment"]["OPENAI_MODEL"]
            == "gpt-6.1-sol"
        ):
            raise error
        return True

    runtime.wait_ready = ready
    assert runtime.apply(request) == (
        "interrupted" if rollback_failure else "rolled_back"
    )
    assert runtime.snapshot()["effective"] == request["previous"]
