"""Choose explicit browser graphics flags without weakening the sandbox."""

from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path

BACKENDS = ("auto", "swiftshader", "egl")


def render_device_available() -> bool:
    return any(
        node.is_char_device() and os.access(node, os.R_OK | os.W_OK)
        for node in Path("/dev/dri").glob("renderD*")
    )


def validate_backend(backend: str) -> None:
    if backend not in BACKENDS:
        raise ValueError(f"Unsupported browser graphics backend: {backend!r}")
    if backend != "egl":
        return
    if not render_device_available():
        raise ValueError(
            "EGL backend requires a readable and writable /dev/dri/renderD* device"
        )
    for library in ("libEGL.so.1", "libGLESv2.so.2"):
        try:
            ctypes.CDLL(library)
        except OSError as error:
            raise ValueError(f"EGL backend requires {library}: {error}") from error


def graphics_arguments(backend: str, *, host_display: bool) -> list[str]:
    if backend not in BACKENDS:
        raise ValueError(f"Unsupported browser graphics backend: {backend!r}")
    args = ["--ignore-gpu-blocklist", "--enable-webgl"]
    if host_display:
        args.append("--ozone-platform=x11")
    selected = "swiftshader" if backend == "auto" and not host_display else backend
    if selected == "swiftshader":
        args.extend(
            ("--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader")
        )
    elif selected == "egl":
        args.extend(("--use-gl=angle", "--use-angle=gl-egl"))
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--host-display", choices=("0", "1"), default="0")
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    try:
        validate_backend(options.backend)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    if not options.check:
        print(
            "\n".join(
                graphics_arguments(
                    options.backend, host_display=options.host_display == "1"
                )
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
