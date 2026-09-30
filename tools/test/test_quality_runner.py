"""Explicit quality suites retain fixtures without collecting sibling modules."""

import importlib
import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize("selected_result", ["pass", "fail", "abort"])
@pytest.mark.parametrize("timing", [False, True])
def test_runner_limits_module_collection_and_preserves_failures(
    tmp_path, monkeypatch, selected_result, timing
):
    monkeypatch.setenv("CROW_DB_URL", "must-not-reach-test-runtime")
    monkeypatch.setenv("CROW_DATA_ROOT_HOST", "must-not-reach-test-runtime")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    runner = importlib.import_module("run_quality_tests")
    project = tmp_path / "project"
    tests = project / "tools" / "test"
    tests.mkdir(parents=True)
    (tests / "unselected_directory").mkdir()
    (project / "conftest.py").write_text(
        textwrap.dedent("""\
            import os
            import pytest

            directory_collections = 0

            def pytest_make_collect_report(collector):
                global directory_collections
                if isinstance(collector, pytest.Dir) and collector.path.name == "test":
                    directory_collections += 1
                    assert directory_collections == 1, "suite directory collected repeatedly"

            @pytest.fixture(autouse=True)
            def isolated_configuration(monkeypatch, pytestconfig):
                from pathlib import Path
                assert pytestconfig.rootpath == Path(__file__).parent
                assert os.environ["FAPAI_DB_ENABLED"] == "0"
                assert os.environ["FAPAI_DB_URL"] == ""
                assert "CROW_DB_URL" not in os.environ
                assert "CROW_DATA_ROOT_HOST" not in os.environ
                assert os.environ["FAPAI_DATA_ROOT"] == os.environ["FAPAI_SOLVER_STATE_DIR"]
                monkeypatch.setenv("CROW_QUALITY_RUNNER_FIXTURE", "loaded")

            def pytest_pycollect_makemodule(module_path, parent):
                if module_path.name == "test_unselected.py":
                    raise AssertionError("unselected sibling collector constructed")

            def pytest_collect_directory(path, parent):
                if path.name == "unselected_directory":
                    raise AssertionError("unselected directory collector constructed")
            """),
        encoding="utf-8",
    )
    (tests / "test_selected.py").write_text(
        "import os\n"
        "def test_selected():\n"
        "    assert os.environ['CROW_QUALITY_RUNNER_FIXTURE'] == 'loaded'\n"
        + (
            "    os._exit(7)\n"
            if selected_result == "abort"
            else f"    assert {selected_result == 'pass'!r}, 'private-failure-payload'\n"
        )
        + "def test_unselected_in_same_file():\n"
        "    raise AssertionError('unselected test executed')\n",
        encoding="utf-8",
    )
    (tests / "manual_case.py").write_text(
        "import os\n"
        "def test_explicit_nonstandard_filename():\n"
        "    assert os.environ['CROW_QUALITY_RUNNER_FIXTURE'] == 'loaded'\n",
        encoding="utf-8",
    )
    (tests / "test_unselected.py").write_text(
        "raise RuntimeError('unselected sibling imported')\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        runner, "__file__", str(project / "scripts" / "run_quality_tests.py")
    )
    monkeypatch.setattr(
        runner,
        "SUITES",
        {"probe": ("test_selected.py::test_selected", "manual_case.py")},
    )
    arguments = ["quality", "--suite", "probe"]
    scripts = project / "scripts"
    scripts.mkdir()
    shutil.copyfile(
        Path(runner.__spec__.origin).with_name("quality_selection.py"),
        scripts / "quality_selection.py",
    )
    report_path = tmp_path / "reports" / "timing.json"
    if timing:
        shutil.copyfile(
            Path(runner.__spec__.origin).with_name("quality_timing.py"),
            scripts / "quality_timing.py",
        )
        arguments.extend(["--timing-report", str(report_path)])
    monkeypatch.setattr(sys, "argv", arguments)
    run = runner.subprocess.run
    outputs = []

    def capture(command, **kwargs):
        result = run(command, **kwargs, capture_output=True, text=True)
        outputs.append(result.stdout + result.stderr)
        return result

    monkeypatch.setattr(runner.subprocess, "run", capture)

    selected_fails = selected_result == "fail"
    expected_exit = 7 if selected_result == "abort" else int(selected_fails)
    assert runner.main() == expected_exit, "\n".join(outputs)
    if selected_result == "abort":
        if timing:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            assert report["complete"] is False
            assert report["stage"] == "test_loop"
            assert report["collection_seconds"] > 0
            assert report["collected_tests"] == 2
            assert "exit_status" not in report
        else:
            assert not report_path.exists()
        return
    expected = "1 failed, 1 passed" if selected_fails else "2 passed"
    assert expected in outputs[0]
    assert "unselected sibling" not in outputs[0]
    if timing:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert "private-failure-payload" not in report_path.read_text(encoding="utf-8")
        assert report["complete"] is True
        assert report["exit_status"] == int(selected_fails)
        assert report["collected_tests"] == report["completed_tests"] == 2
        assert report["phase_counts"] == {"setup": 2, "call": 2, "teardown": 2}
        assert report["session_seconds"] >= report["collection_seconds"] > 0
        assert report["test_loop_seconds"] >= sum(report["phase_seconds"].values()) > 0
        assert set(report["files"]) == {
            "tools/test/test_selected.py",
            "tools/test/manual_case.py",
        }
        assert sum(row["phases"] for row in report["files"].values()) == 6
    else:
        assert not report_path.exists()
