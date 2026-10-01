"""用隔离 release 和假 Compose 验证跨版本回滚，不操作真实容器。"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", ["legacy", "current", "missing-helper"])
def test_release_validation_preserves_legacy_rollback(tmp_path, kind):
    bash = shutil.which("bash")
    if not bash or os.name == "nt":
        pytest.skip("Native POSIX Bash required")
    source = (ROOT / "ops/pc2-linux/deploy.sh").read_text(encoding="utf-8")
    start = source.index("validate_release_tree() {")
    function = source[start : source.index("\n}", start) + 2]
    for name in (
        "Dockerfile",
        "ops/pc2-linux/Dockerfile.browser",
        "ops/pc2-linux/compose.yaml",
        "tools/pc2_linux_healthcheck.py",
        "requirements.lock",
        "ops/pc2-linux/process-supervisor.sh",
        "ops/pc2-linux/start-browser-solver.sh",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    if kind != "legacy":
        (tmp_path / "ops/pc2-linux/process-supervisor.sh").write_text(
            'source "$root/scripts/project-environment.sh"\n', encoding="utf-8"
        )
    if kind == "current":
        helper = tmp_path / "scripts/project-environment.sh"
        helper.parent.mkdir()
        helper.write_text("true\n", encoding="utf-8")
    result = subprocess.run(
        [
            bash,
            "-c",
            "set -eu; compose_for() { echo compose-validated; };\n"
            + function
            + '\nvalidate_release_tree "$1"',
            "fixture",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if kind == "missing-helper":
        assert result.returncode != 0
        assert "compose-validated" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "compose-validated"
