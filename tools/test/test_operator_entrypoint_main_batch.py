import os
import subprocess
from pathlib import Path

import pytest

from tools.test.operator_entrypoint_smoke_context import (
    _assert_stub_invocation,
    _copy_repo_batch_to_fake_repo,
    _run_batch,
    _write_fake_python_cmd,
    _write_fake_python_cmd_with_exit,
    _write_real_python_target,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requires Windows cmd.exe")


def test_main_batch_respects_predefined_python_cmd(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "main.bat")
    log_path = fake_repo / "main-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    _write_real_python_target(fake_repo / "src" / "server.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "main.bat", env)

    assert result.returncode == 0
    _assert_stub_invocation(
        log_path, "tools/run_collection_api.py", expected_cwd=fake_repo
    )


def test_data_fixer_batch_respects_predefined_python_cmd(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "data_fixer.bat")
    log_path = fake_repo / "data-fixer-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    _write_real_python_target(fake_repo / "src" / "data_fixer.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "data_fixer.bat", env)

    assert result.returncode == 0
    _assert_stub_invocation(log_path, "src/data_fixer.py", expected_cwd=fake_repo)


def test_main_batch_returns_python_exit_code(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "main.bat")
    log_path = fake_repo / "main-exit-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 23)
    _write_real_python_target(fake_repo / "src" / "server.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "main.bat", env)

    assert result.returncode == 23
    _assert_stub_invocation(
        log_path, "tools/run_collection_api.py", expected_cwd=fake_repo
    )


def test_data_fixer_batch_returns_python_exit_code(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "data_fixer.bat")
    log_path = fake_repo / "data-fixer-exit-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 24)
    _write_real_python_target(fake_repo / "src" / "data_fixer.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "data_fixer.bat", env)

    assert result.returncode == 24
    _assert_stub_invocation(log_path, "src/data_fixer.py", expected_cwd=fake_repo)


def test_main_batch_resumes_parent_after_cmd_python_wrapper(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "main.bat")
    log_path = fake_repo / "main-parent-resume-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 25)
    _write_real_python_target(fake_repo / "src" / "server.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "main.bat", env)

    assert result.returncode == 25
    _assert_stub_invocation(
        log_path, "tools/run_collection_api.py", expected_cwd=fake_repo
    )
    assert "[INFO] main.bat finished with exit code 25" in result.stdout


def test_data_fixer_batch_resumes_parent_after_cmd_python_wrapper(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "data_fixer.bat")
    log_path = fake_repo / "data-fixer-parent-resume-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 26)
    _write_real_python_target(fake_repo / "src" / "data_fixer.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "data_fixer.bat", env)

    assert result.returncode == 26
    _assert_stub_invocation(log_path, "src/data_fixer.py", expected_cwd=fake_repo)
    assert "[INFO] data_fixer.bat finished with exit code 26" in result.stdout


def test_main_batch_smoke_runs_against_actual_repo_with_stub_python(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    log_path = tmp_path / "actual-main-log.txt"
    fake_python = _write_fake_python_cmd(tmp_path, log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = subprocess.run(
        ["cmd", "/c", str(repo_root / "auto" / "main.bat")],
        cwd=str(repo_root),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    _assert_stub_invocation(
        log_path,
        "tools/run_collection_api.py",
        expected_cwd=repo_root,
    )


def test_data_fixer_batch_smoke_runs_against_actual_repo_with_stub_python(
    tmp_path: Path,
):
    repo_root = Path(__file__).resolve().parents[2]
    log_path = tmp_path / "actual-data-fixer-log.txt"
    fake_python = _write_fake_python_cmd(tmp_path, log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = subprocess.run(
        ["cmd", "/c", str(repo_root / "auto" / "data_fixer.bat")],
        cwd=str(repo_root),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    _assert_stub_invocation(
        log_path,
        "src/data_fixer.py",
        expected_cwd=repo_root,
    )
