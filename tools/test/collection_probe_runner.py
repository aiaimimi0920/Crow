"""Parallel fresh interpreters, each with its own collection storage root."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SOURCES = ("catalog_x", "taobao_sf")


def run_source_probes(
    probe: Path, root: Path, *, timeout: int
) -> dict[str, subprocess.CompletedProcess[str]]:
    def run(source: str) -> subprocess.CompletedProcess[str]:
        directory = root / source
        directory.mkdir()
        return subprocess.run(
            [sys.executable, str(probe), str(directory), source],
            cwd=directory,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        return dict(zip(SOURCES, pool.map(run, SOURCES), strict=True))
