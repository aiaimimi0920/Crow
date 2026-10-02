"""Shared host X11 sockets must survive non-root browser startup."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/pc2-linux/start-browser-solver.sh"


def select_display(root, requested=":99"):
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("Native POSIX Bash required")
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("crow_select_xvfb_display() {")
    function = source[start : source.index("\n}", start) + 2]
    return subprocess.run(
        [
            "bash",
            "-c",
            "set -eu;\n" + function + '\ncrow_select_xvfb_display "$1" "$2"',
            "fixture",
            requested,
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_xvfb_launcher_never_unlinks_shared_display_artifacts():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'rm -f "$display_lock" "$display_socket"' not in source
    assert 'display="$(crow_select_xvfb_display "$display")"' in source
    assert source.index('export DISPLAY="$display"') > source.index(
        'display="$(crow_select_xvfb_display "$display")"'
    )


@pytest.mark.parametrize("kind", ["socket", "lock", "socket-symlink", "lock-symlink"])
def test_existing_display_artifact_is_preserved_and_skipped(tmp_path, kind):
    if os.name == "nt":
        pytest.skip("Native POSIX symlinks and Bash required")
    (tmp_path / ".X11-unix").mkdir()
    path = tmp_path / (".X11-unix/X99" if kind.startswith("socket") else ".X99-lock")
    if kind.endswith("symlink"):
        path.symlink_to(tmp_path / "missing-target")
    else:
        path.write_bytes(b"foreign-display-do-not-remove")
    before = path.lstat()
    result = select_display(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ":100"
    assert path.lstat() == before
    if not path.is_symlink():
        assert path.read_bytes() == b"foreign-display-do-not-remove"


def test_requested_unused_display_is_unchanged(tmp_path):
    result = select_display(tmp_path, ":104")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ":104"


def test_exhausted_display_range_fails_without_deleting_locks(tmp_path):
    for number in range(99, 163):
        (tmp_path / f".X{number}-lock").write_bytes(b"preserve")
    result = select_display(tmp_path)
    assert result.returncode != 0
    assert "No unused Xvfb display" in result.stderr
    assert len(list(tmp_path.glob(".X*-lock"))) == 64
    assert all(path.read_bytes() == b"preserve" for path in tmp_path.glob(".X*-lock"))


@pytest.mark.parametrize("requested", ["remote:99", ":99.0", ":999999999999"])
def test_invalid_xvfb_display_is_rejected(tmp_path, requested):
    result = select_display(tmp_path, requested)
    assert result.returncode != 0
    assert "Invalid Xvfb display" in result.stderr
