"""Retained same-label backups must never be Compose recreation candidates."""

from copy import deepcopy

import pytest

from tools.pc2_container_inventory import require_compose_safe_inventory
from tools.pc2_settings_release import ReleaseRuntime
from tools.pc2_settings_runtime import SettingsRuntime
from tools.test.collection_settings_fixtures import FakeDocker
from tools.test.test_pc2_settings_runtime import command


def add_backup(docker, service="pc2-analysis-1", status="exited"):
    row = deepcopy(docker.rows[service])
    row.update(Id="b" * 64, Name=row["Name"] + "-arbitrary-retained-name")
    row["State"] = {"Running": False, "Status": status}
    docker.rows["retained"] = row


def runtime_for(tmp_path, docker):
    return SettingsRuntime(
        tmp_path, [], runner=docker, clock=lambda: docker.time, sleep=docker.sleep
    )


@pytest.mark.parametrize("service", ["pc2-analysis-1", "pc2-detail-3"])
@pytest.mark.parametrize("status", ["created", "exited", "dead"])
def test_changed_or_removed_backup_rejected_before_any_mutation(
    tmp_path, service, status
):
    docker = FakeDocker()
    add_backup(docker, service, status)
    before = deepcopy(docker.rows)
    runtime = runtime_for(tmp_path, docker)
    assert runtime.apply(command()) == "rejected"
    assert docker.rows == before
    assert not list(tmp_path.iterdir())
    assert not any(call[0] == "stop" or "up" in call for call in docker.calls)


def test_new_service_backup_also_blocks_expansion(tmp_path):
    docker = FakeDocker()
    docker.start("pc2-analysis-5", docker.model["services"]["pc2-analysis-1"])
    add_backup(docker, "pc2-analysis-5")
    docker.rows.pop("pc2-analysis-5")
    runtime = runtime_for(tmp_path, docker)
    assert runtime.apply(command()) == "rejected"
    assert not any("up" in call or call[0] == "stop" for call in docker.calls)


def test_unrelated_backup_does_not_block_scoped_apply(tmp_path):
    docker = FakeDocker()
    add_backup(docker, "pc2-seed-1")
    assert runtime_for(tmp_path, docker).apply(command()) == "applied"


def test_stopped_canonical_is_not_a_retained_backup():
    docker = FakeDocker()
    row = docker.rows["pc2-analysis-1"]
    row["State"] = {"Running": False, "Status": "exited"}
    require_compose_safe_inventory(list(docker.rows.values()), ["pc2-analysis-1"])


def test_active_noncanonical_is_still_rejected():
    docker = FakeDocker()
    add_backup(docker)
    docker.rows["retained"]["State"] = {"Running": True, "Status": "running"}
    with pytest.raises(ValueError, match="Noncanonical"):
        require_compose_safe_inventory(list(docker.rows.values()), ["pc2-analysis-1"])


def test_direct_up_guard_catches_backup_created_after_preflight(tmp_path):
    docker = FakeDocker()
    runtime = runtime_for(tmp_path, docker)
    runtime.require_compose_safe(["pc2-analysis-1"])
    add_backup(docker)
    with pytest.raises(ValueError, match="exact-ID"):
        runtime.compose(tmp_path / "unused.json", ["up", "-d", "pc2-analysis-1"])
    assert not any("up" in call for call in docker.calls)


def test_rollback_does_not_bypass_backup_guard(tmp_path, monkeypatch):
    docker = FakeDocker()
    runtime = runtime_for(tmp_path, docker)

    def fail_readiness(_model):
        add_backup(docker)
        return False

    monkeypatch.setattr(runtime, "wait_ready", fail_readiness)
    assert runtime.apply(command()) == "interrupted"
    ups = [call for call in docker.calls if "up" in call]
    assert len(ups) == 1 and "after.json" in " ".join(ups[0])
    assert not runtime.active.exists()
    assert (tmp_path / command()["request_id"] / "before.json").exists()


@pytest.mark.parametrize("browser_only", [False, True])
def test_release_rejects_before_journal_or_image_operations(tmp_path, browser_only):
    docker = FakeDocker()
    if browser_only:
        service = "pc2-browser-solver"
        docker.start(service, {**docker.model["services"][service], "volumes": []})
    else:
        service = "pc2-analysis-1"
    add_backup(docker, service)
    runtime = runtime_for(tmp_path, docker)
    release = ReleaseRuntime(runtime)
    arguments = (
        ["up", "-d", "--no-deps", "pc2-browser-solver"]
        if browser_only
        else ["up", "-d", "--remove-orphans"]
    )
    with pytest.raises(ValueError, match="exact-ID"):
        release.compose([], arguments)
    assert not release.journal.exists()
    assert not list(tmp_path.iterdir())
    assert not any("up" in call or call[0] == "image" for call in docker.calls)
