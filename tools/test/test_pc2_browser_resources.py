from pathlib import Path

OPS_ROOT = Path(__file__).resolve().parents[2] / "ops" / "pc2-linux"


def test_shared_browser_has_configurable_bounded_cpu_headroom() -> None:
    compose = (OPS_ROOT / "compose.yaml").read_text(encoding="utf-8")
    browser = compose.split("  pc2-browser-solver:", 1)[1].split("  pc2-seed-1:", 1)[0]

    assert "cpus: ${FAPAI_BROWSER_CPUS:-3.0}" in browser
    assert "mem_limit: 2g" in browser
    assert "pids_limit: 512" in browser
    assert "cpus: 0.75" in compose.split("services:", 1)[0]
    example = (OPS_ROOT / "env.example").read_text(encoding="utf-8")
    assert "FAPAI_BROWSER_CPUS=3.0" in example
