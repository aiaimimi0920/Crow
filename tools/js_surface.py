from __future__ import annotations

from pathlib import Path
import subprocess


_EXCLUDE_DIRS = {
    "node_modules",
    "dist",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    ".debug",
    "output",
    "target",
    ".codex-temp",
    ".memsearch",
    ".playwright-cli",
    "graphify-out",
}

def repo_js_syntax_check_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*.js")):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def node_check_repo_js_surface(repo_root: Path) -> list[tuple[Path, int, str, str]]:
    failures: list[tuple[Path, int, str, str]] = []
    for path in repo_js_syntax_check_files(repo_root):
        result = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            failures.append((path, result.returncode, result.stdout, result.stderr))
    return failures
