"""Final model validation uses captured synthetic output and never starts Docker."""

import json
from types import SimpleNamespace

import pytest

from tools.compose_arguments import ComposeEnvironmentError, compose_inputs
from tools.compose_service_environment import validate_service_environment


def test_final_model_uses_exact_selector_prefix_without_operational_arguments(tmp_path):
    arguments = [
        "-pfixture",
        "--env-file",
        "synthetic.env",
        "-ffirst.json",
        "-f=second.json",
        "--project-directory",
        str(tmp_path),
        "up",
        "-d",
        "worker",
    ]
    inputs = compose_inputs(arguments, tmp_path)
    calls = []

    def runner(command, **options):
        calls.append((command, options))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "services": {
                        "worker": {
                            "environment": {"CROW_TEST": "same", "FAPAI_TEST": "same"}
                        }
                    }
                }
            ),
        )

    validate_service_environment(
        inputs.global_arguments, {"PATH": "fixture"}, runner=runner
    )
    assert calls[0][0] == [
        "docker",
        "compose",
        *arguments[:-3],
        "config",
        "--format",
        "json",
    ]
    assert calls[0][1]["capture_output"] and calls[0][1]["env"] == {"PATH": "fixture"}
    assert calls[0][1]["encoding"] == "utf-8"
    assert "cwd" not in calls[0][1]


def test_container_layer_conflict_reports_only_keys_and_legacy_wire_guidance():
    model = {
        "services": {
            "fixture": {
                "environment": {
                    "CROW_TEST": "private-file",
                    "FAPAI_TEST": "private-service",
                }
            }
        }
    }
    with pytest.raises(ComposeEnvironmentError) as error:
        validate_service_environment(
            [],
            {},
            runner=lambda *_a, **_kw: SimpleNamespace(
                returncode=0, stdout=json.dumps(model)
            ),
        )
    assert "CROW_TEST" in str(error.value) and "FAPAI_TEST" in str(error.value)
    assert "legacy wire" in str(error.value) and "private" not in str(error.value)


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="private", stderr="private"),
        SimpleNamespace(returncode=0, stdout="private"),
        SimpleNamespace(returncode=0, stdout='{"services": []}'),
        SimpleNamespace(returncode=0, stdout='{"name": "invalid"}'),
    ],
)
def test_invalid_or_failed_config_diagnostics_never_echo_output(result):
    with pytest.raises(ComposeEnvironmentError) as error:
        validate_service_environment([], {}, runner=lambda *_a, **_kw: result)
    assert "private" not in str(error.value)
