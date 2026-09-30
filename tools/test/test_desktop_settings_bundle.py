"""Exercise the exact standalone helper closure, without repository import fallback."""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_standalone_bundle_imports_and_sanitizes_missing_config(tmp_path):
    root = Path(__file__).resolve().parents[2]
    names = [
        "tools/desktop_settings_client.py",
        "tools/desktop_runtime_config.py",
        "tools/desktop_environment.py",
        "tools/pc1_desktop_recovery.py",
        "src/auth_recovery_codes.py",
        "src/auth_snapshot_contract.py",
        "src/collection_api_credentials.py",
        "src/collection_settings_schema.py",
        "src/collection_engine_restart.py",
        "src/project_data_paths.py",
        "src/project_environment.py",
        "src/collection_operator_actions.py",
        "src/llm_analysis_policy.py",
    ]
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    result = subprocess.run(
        [sys.executable, "-I", str(tmp_path / names[0])],
        cwd=tmp_path,
        input=json.dumps({"action": "config"}),
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0 and not result.stderr
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": "control_transport_unavailable",
    }
