"""Synthetic, offline coverage of the source-text-free SARIF inventory."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import summarize_codeql_results as summary

pytestmark = [pytest.mark.security, pytest.mark.unit]


def _result(rule_id: str = "py/incomplete-url-substring-sanitization") -> dict:
    return {
        "ruleId": rule_id,
        "message": {
            "text": "SYNTHETIC_PRIVATE_MESSAGE https://secret.invalid/?token=PRIVATE"
        },
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": "src/example.py",
                        "uriBaseId": "%SRCROOT%",
                    },
                    "region": {
                        "startLine": 12,
                        "snippet": {"text": "SYNTHETIC_PRIVATE_SNIPPET"},
                    },
                }
            }
        ],
        "codeFlows": [{"message": {"text": "SYNTHETIC_PRIVATE_FLOW"}}],
        "partialFingerprints": {"secret": "SYNTHETIC_PRIVATE_FINGERPRINT"},
    }


def _payload(results: list | None = None) -> dict:
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeQL",
                        "rules": [
                            {
                                "id": "py/incomplete-url-substring-sanitization",
                                "properties": {"security-severity": "7.8"},
                                "defaultConfiguration": {"level": "warning"},
                                "fullDescription": {
                                    "text": "SYNTHETIC_PRIVATE_DESCRIPTION"
                                },
                            }
                        ],
                    }
                },
                "invocations": [{"executionSuccessful": True}],
                "results": [_result()] if results is None else results,
            }
        ],
    }


def _write(directory: Path, payload: dict, name: str = "python.sarif") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_only_allowlisted_fields_are_emitted(tmp_path: Path) -> None:
    _write(tmp_path, _payload())
    report = summary.summarize(tmp_path)
    assert report["results"] == [
        {
            "rule_id": "py/incomplete-url-substring-sanitization",
            "path": "src/example.py",
            "line": 12,
            "level": "warning",
            "security_severity": "7.8",
        }
    ]
    text = json.dumps(report)
    for private in ("SYNTHETIC_PRIVATE", "https://", "token=", str(tmp_path)):
        assert private not in text
    assert report["count_kind"] == "sarif_results_not_github_open_alerts"


def test_multiple_files_runs_and_truncation_count_every_result(tmp_path: Path) -> None:
    payload = _payload([_result(), _result()])
    payload["runs"].append(deepcopy(payload["runs"][0]))
    _write(tmp_path, payload)
    _write(tmp_path / "nested", _payload(), "javascript.sarif")
    report = summary.summarize(tmp_path, max_results=2)
    assert (report["file_count"], report["run_count"], report["result_count"]) == (
        2,
        3,
        5,
    )
    assert (report["emitted_count"], report["omitted_count"], report["truncated"]) == (
        2,
        3,
        True,
    )
    assert report["by_rule"] == [{"rule_id": _result()["ruleId"], "count": 5}]
    assert report["by_severity"] == [
        {"level": "warning", "security_severity": "7.8", "count": 5}
    ]


def test_empty_results_are_valid_and_parse_warnings_are_not_failures(
    tmp_path: Path,
) -> None:
    payload = _payload([])
    payload["runs"][0]["invocations"][0]["toolExecutionNotifications"] = [
        {"level": "warning", "message": {"text": "PRIVATE"}}
    ]
    _write(tmp_path, payload)
    report = summary.summarize(tmp_path)
    assert report["result_count"] == 0
    assert report["results"] == []
    assert report["truncated"] is False


@pytest.mark.parametrize(
    "notification",
    [None, "toolExecutionNotifications", "toolConfigurationNotifications"],
)
def test_failed_execution_never_produces_zero(
    tmp_path: Path, notification: str | None
) -> None:
    payload = _payload([])
    invocation = payload["runs"][0]["invocations"][0]
    if notification:
        invocation[notification] = [{"level": "error", "message": {"text": "PRIVATE"}}]
    else:
        invocation["executionSuccessful"] = False
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError, match="^scan_execution_failed$"):
        summary.summarize(tmp_path)


@pytest.mark.parametrize(
    "field,value", [("runs", []), ("runs", None), ("version", "1.0")]
)
def test_invalid_document_is_an_error(
    tmp_path: Path, field: str, value: object
) -> None:
    payload = _payload()
    payload[field] = value
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError):
        summary.summarize(tmp_path)


def test_missing_results_is_an_error(tmp_path: Path) -> None:
    payload = _payload()
    del payload["runs"][0]["results"]
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError, match="^missing_results$"):
        summary.summarize(tmp_path)


@pytest.mark.parametrize(
    "uri",
    [
        "/home/private/example.py",
        "file:///home/private/example.py",
        "https://secret.invalid/file.py",
        "../private.py",
        "src/../private.py",
        "src/%2e%2e/private.py",
        "src/%252e%252e/private.py",
        "C:/private.py",
        "src\\private.py",
        "src/file.py?token=PRIVATE",
        "src/file.py#PRIVATE",
        "src/%00private.py",
        "src/%FF.py",
        "src//private.py",
        "src/./private.py",
        "x" * 2049,
    ],
)
def test_unsafe_locations_are_rejected(tmp_path: Path, uri: str) -> None:
    payload = _payload()
    payload["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]["uri"] = uri
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError, match="^invalid_location$"):
        summary.summarize(tmp_path)


@pytest.mark.parametrize("line", [True, 0, -1, 1.2, "12", 10_000_001])
def test_invalid_line_is_rejected(tmp_path: Path, line: object) -> None:
    payload = _payload()
    payload["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"][
        "startLine"
    ] = line
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError, match="^invalid_location$"):
        summary.summarize(tmp_path)


@pytest.mark.parametrize(
    "identifier",
    ["https://secret.invalid", "py/test?token=PRIVATE", "x" * 161, True, None],
)
def test_invalid_rule_identifiers_are_rejected(
    tmp_path: Path, identifier: object
) -> None:
    payload = _payload()
    payload["runs"][0]["results"][0]["ruleId"] = identifier
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError):
        summary.summarize(tmp_path)


@pytest.mark.parametrize(
    "severity", [True, "SECRET", "https://secret.invalid", "NaN", 11, -1, {}]
)
def test_invalid_security_severity_is_rejected(
    tmp_path: Path, severity: object
) -> None:
    payload = _payload()
    payload["runs"][0]["tool"]["driver"]["rules"][0]["properties"][
        "security-severity"
    ] = severity
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError):
        summary.summarize(tmp_path)


def test_rule_and_artifact_indexes_and_level_override(tmp_path: Path) -> None:
    payload = _payload()
    run = payload["runs"][0]
    result = run["results"][0]
    del result["ruleId"]
    result.update(ruleIndex=0, level="error")
    result["locations"][0]["physicalLocation"]["artifactLocation"] = {"index": 0}
    run["artifacts"] = [{"location": {"uri": "src/my%20file.py"}}]
    _write(tmp_path, payload)
    row = summary.summarize(tmp_path)["results"][0]
    assert row["path"] == "src/my file.py"
    assert row["level"] == "error"


def test_invalid_result_after_output_cap_still_fails(tmp_path: Path) -> None:
    payload = _payload([_result(), _result()])
    payload["runs"][0]["results"][1]["ruleId"] = "PRIVATE"
    _write(tmp_path, payload)
    with pytest.raises(summary.SummaryError):
        summary.summarize(tmp_path, max_results=1)


@pytest.mark.parametrize("limit", [0, -1, True, 5001])
def test_invalid_output_limit_is_rejected(tmp_path: Path, limit: int) -> None:
    with pytest.raises(summary.SummaryError, match="^invalid_output_limit$"):
        summary.summarize(tmp_path, max_results=limit)


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_FILES",
        "MAX_FILE_BYTES",
        "MAX_TOTAL_BYTES",
        "MAX_RUNS",
        "MAX_INPUT_RESULTS",
        "MAX_RULES",
        "MAX_DIRECTORY_ENTRIES",
    ],
)
def test_input_limits_fail_without_incomplete_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    _write(tmp_path, _payload())
    monkeypatch.setattr(summary, limit, 0)
    with pytest.raises(summary.SummaryError):
        summary.summarize(tmp_path)


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    source = _write(tmp_path / "source", _payload())
    target = tmp_path / "input"
    target.mkdir()
    (target / "link.sarif").symlink_to(source)
    with pytest.raises(summary.SummaryError, match="^unsafe_input$"):
        summary.summarize(target)


@pytest.mark.parametrize("contents", [None, "not JSON PRIVATE", "{}"])
def test_cli_errors_never_include_input_data(
    tmp_path: Path, capsys: pytest.CaptureFixture, contents: str | None
) -> None:
    if contents is not None:
        (tmp_path / "PRIVATE.sarif").write_text(contents)
    assert summary.main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert set(json.loads(captured.out)) == {"error"}
    assert not captured.err
    assert "PRIVATE" not in captured.out
    assert str(tmp_path) not in captured.out


def test_cli_bad_argument_does_not_echo_value(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as error:
        summary.main(["PRIVATE", "--max-results", "PRIVATE_TOKEN"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "invalid_arguments"}
    assert not captured.err


def test_cli_findings_are_successful_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _write(tmp_path, _payload())
    assert summary.main([str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["result_count"] == 1
