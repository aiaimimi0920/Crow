import json
import subprocess

import pytest

from tools.pc2_collection_controller import unavailable_event


def test_settings_drift_is_distinguishable_without_weakening_the_gate():
    event = json.loads(
        unavailable_event(
            ValueError(
                "Live settings drift from provisioned Compose; refusing to overwrite"
            )
        )
    )
    assert event["reason"] == "settings_drift"
    assert event["operation_replayed"] is False


@pytest.mark.parametrize(
    "error",
    [
        ValueError("secret-token-in-invalid-config"),
        OSError("secret-token-in-url"),
        subprocess.TimeoutExpired(["docker", "secret-token-in-command"], 20),
        subprocess.CalledProcessError(1, ["secret-token-in-command"]),
    ],
)
def test_diagnostics_never_echo_exception_text_or_commands(error):
    output = unavailable_event(error)
    assert "secret-token" not in output
    assert json.loads(output)["operation_replayed"] is False
