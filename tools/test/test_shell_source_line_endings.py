"""验证 Windows checkout 不会破坏要复制进 Linux 镜像的 Bash 入口。"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/project-environment.sh",
        "ops/pc2-linux/start-browser-solver.sh",
        "ops/pc2-linux/process-supervisor.sh",
    ],
)
def test_linux_entrypoints_are_utf8_lf_in_checkout(relative):
    payload = (ROOT / relative).read_bytes()
    payload.decode("utf-8")
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in payload
    assert "*.sh text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
