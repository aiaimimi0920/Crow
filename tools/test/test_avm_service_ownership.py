"""The service export namespace cannot overwrite unrelated native dependencies."""

import types

from src.avm import service, service_health


def test_service_namespace_assignment_does_not_replace_health_provider(monkeypatch):
    monkeypatch.setattr(
        service_health, "get_effective_weighting", lambda: {"distance_power": 1.7}
    )
    monkeypatch.setattr(
        service,
        "get_effective_weighting",
        lambda: {"distance_power": 99},
        raising=False,
    )
    instance = service.AVMService(data_dir="unused")
    health = instance.health_snapshot(lightweight=True)
    assert health["active_weighting"] == {"distance_power": 1.7}
    assert type(service) is types.ModuleType
    assert health["model_version"] == instance.model_version() == service.MODEL_VERSION
