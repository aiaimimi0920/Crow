"""Exercise the NAS shell workflow on disposable files, never a real database."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_rotation_preserves_rollback_and_check_requires_the_published_copy(tmp_path):
    root = Path(__file__).resolve().parents[2]
    git = shutil.which("git")
    bash = (Path(git).resolve().parents[1] / "bin/bash.exe") if os.name == "nt" and git else shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash unavailable")
    nas = tmp_path / "nas"
    backups = nas / "backups/postgres"
    scheduled = backups / "scheduled"
    scheduled.mkdir(parents=True)
    tools = tmp_path / "bin"
    tools.mkdir()

    # Prefer these fixtures even on hosts with live Docker or PostgreSQL installed.
    fakes = {"docker": "exit 1", "pg_dump": 'head -c 2048 /dev/zero > "${!#}"',
             "pg_restore": "printf '%s\\n' 1 2 3 4 5"}
    if os.name == "nt":
        fakes["flock"] = "exit 0"  # Git Bash does not ship Linux flock.
    for name, body in fakes.items():
        path = tools / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o700)
    legacy = backups / "fapaifang-20000101-000000.dump"
    legacy.write_bytes(b"rollback" * 150)
    for day in range(1, 7):
        (scheduled / f"fapaifang-2000010{day}-000000.dump").write_bytes(bytes(1100))
    env = dict(os.environ, CROW_NAS_DATA_ROOT=nas.as_posix(),
               CROW_NAS_ENV_FILE=(tmp_path / "absent.env").as_posix(),
               PATH=str(tools) + os.pathsep + os.environ["PATH"])

    def run(script):
        return subprocess.run([bash, (root / "scripts" / script).as_posix()], env=env,
                              capture_output=True, text=True, timeout=25, check=False)

    backup = run("backup-nas-postgres.sh")
    assert backup.returncode == 0, backup.stderr
    assert legacy.read_bytes() == b"rollback" * 150
    check = "check-nas-postgres-backup-health.sh"
    good = run(check)
    assert good.returncode == 0, good.stderr
    data = json.loads(good.stdout)
    assert data["retained_backups"] == 4 and data["pruned_backups"] == 3
    target = scheduled / data["latest_backup_file"]
    target.write_bytes(bytes(1024))
    bad = run(check)
    assert bad.returncode == 1 and json.loads(bad.stdout)["reason"] == "backup_file_mismatch"
