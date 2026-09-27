"""Run independent crash processes concurrently; recovery assertions stay serial."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run_crash_probes(script: Path, cases: list[tuple[str, ...]], root: Path):
    def probe(case):
        directory = root.joinpath(*case)
        directory.mkdir(parents=True)
        env = dict(os.environ)
        env.update(
            FAPAI_SOLVER_STATE_DIR=str(directory),
            FAPAI_DATA_ROOT=str(directory),
            FAPAI_DB_ENABLED="0",
            FAPAI_DB_URL="",
            FAPAI_NAS_AUTH_RECOVERY_ENABLED="0",
        )
        child = subprocess.run(
            [sys.executable, str(script), *case],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return child, directory

    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(cases, pool.map(probe, cases), strict=True))
