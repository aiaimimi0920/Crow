import os
import sys
from pathlib import Path

import pytest

from src.compose_environment import prepare_environment
from tools import pc2_browser_graphics as graphics

OPS_ROOT = Path(__file__).resolve().parents[2] / "ops" / "pc2-linux"


@pytest.mark.parametrize("host_display", [False, True])
@pytest.mark.parametrize("backend", graphics.BACKENDS)
def test_graphics_argument_matrix(backend: str, host_display: bool) -> None:
    args = graphics.graphics_arguments(backend, host_display=host_display)
    software = backend == "swiftshader" or (backend == "auto" and not host_display)
    assert ("--enable-unsafe-swiftshader" in args) == software
    assert ("--use-angle=swiftshader" in args) == software
    assert ("--use-angle=gl-egl" in args) == (backend == "egl")
    assert ("--ozone-platform=x11" in args) == host_display
    assert "--enable-webgl" in args
    assert not any("sandbox" in arg for arg in args)


def test_invalid_backend_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        graphics.validate_backend("vulkan")
    with pytest.raises(ValueError, match="Unsupported"):
        graphics.graphics_arguments("vulkan", host_display=False)


def test_egl_requires_accessible_render_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graphics, "render_device_available", lambda: False)
    with pytest.raises(ValueError, match="readable and writable"):
        graphics.validate_backend("egl")


@pytest.mark.parametrize("usable", [None, 0, 1])
def test_render_nodes_require_character_device_and_rw_access(
    monkeypatch: pytest.MonkeyPatch, usable: int | None
) -> None:
    class Node:
        def __init__(self, number: int, character: bool = True) -> None:
            self.number = number
            self.character = character

        def is_char_device(self) -> bool:
            return self.character

    nodes = [Node(0), Node(1), Node(2, character=False)]
    monkeypatch.setattr(graphics.Path, "glob", lambda self, pattern: nodes)
    monkeypatch.setattr(
        graphics.os,
        "access",
        lambda node, mode: mode == os.R_OK | os.W_OK and node.number == usable,
    )
    assert graphics.render_device_available() == (usable is not None)


@pytest.mark.parametrize("missing", ["libEGL.so.1", "libGLESv2.so.2"])
def test_egl_requires_runtime_libraries(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setattr(graphics, "render_device_available", lambda: True)

    def load(library: str) -> object:
        if library == missing:
            raise OSError("missing library")
        return object()

    monkeypatch.setattr(graphics.ctypes, "CDLL", load)
    with pytest.raises(ValueError, match=missing):
        graphics.validate_backend("egl")


def test_egl_checks_both_libraries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graphics, "render_device_available", lambda: True)
    loaded: list[str] = []
    monkeypatch.setattr(graphics.ctypes, "CDLL", lambda library: loaded.append(library))
    graphics.validate_backend("egl")
    assert loaded == ["libEGL.so.1", "libGLESv2.so.2"]


@pytest.mark.parametrize("backend", ["auto", "swiftshader"])
def test_compatibility_backends_do_not_require_gpu(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    monkeypatch.setattr(
        graphics,
        "render_device_available",
        lambda: pytest.fail("unexpected device check"),
    )
    graphics.validate_backend(backend)


def test_browser_scoped_configuration_and_image_contract() -> None:
    compose = (OPS_ROOT / "compose.yaml").read_text(encoding="utf-8")
    browser = compose.split("  pc2-browser-solver:", 1)[1].split("  pc2-seed-1:", 1)[0]
    workers = compose.replace(browser, "")
    assert (
        "FAPAI_BROWSER_GRAPHICS_BACKEND: ${FAPAI_BROWSER_GRAPHICS_BACKEND:-auto}"
        in browser
    )
    for key in ("FAPAI_HOST_VIDEO_GID", "FAPAI_HOST_RENDER_GID"):
        assert f"${{{key}:-1000}}" in browser
        assert key not in workers
    for constraint in ("no-new-privileges:true", "apparmor=", "seccomp=", "cap_drop:"):
        assert constraint in browser
    dockerfile = (OPS_ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    for package in ("libegl1", "libegl-mesa0", "libgles2"):
        assert package in dockerfile
    for name in ("Dockerfile.browser", "Dockerfile.auth-recovery"):
        assert (
            "COPY tools/pc2_browser_graphics.py /app/tools/pc2_browser_graphics.py"
            in (OPS_ROOT / name).read_text(encoding="utf-8")
        )
    start = (OPS_ROOT / "start-browser-solver.sh").read_text(encoding="utf-8")
    assert start.index("--check") < start.index("rm -f")
    assert 'mapfile -t browser_graphics_args <<< "$graphics_output"' in start


def test_graphics_keys_use_existing_compose_alias_bridge() -> None:
    inputs = {
        "CROW_BROWSER_GRAPHICS_BACKEND": "egl",
        "CROW_HOST_VIDEO_GID": "44",
        "CROW_HOST_RENDER_GID": "992",
    }
    resolved = prepare_environment(OPS_ROOT, process=inputs, file_values={})
    for key, value in inputs.items():
        assert resolved[key] == resolved["FAPAI_" + key[5:]] == value


def test_cli_auto_emits_software_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["graphics", "--backend", "auto"])
    assert graphics.main() == 0
    assert "--use-angle=swiftshader" in capsys.readouterr().out


def test_cli_missing_device_exits_before_emitting_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["graphics", "--backend", "egl", "--check"])
    monkeypatch.setattr(graphics, "render_device_available", lambda: False)
    with pytest.raises(SystemExit) as error:
        graphics.main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "readable and writable" in captured.err
