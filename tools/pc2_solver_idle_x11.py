"""Read the owned foreground X11 browser and emit motion only, never clicks."""

from __future__ import annotations

import ctypes as c
import re
from pathlib import Path


class _IdleInfo(c.Structure):
    _fields_ = [
        ("window", c.c_ulong),
        ("state", c.c_int),
        ("kind", c.c_int),
        ("til_or_since", c.c_ulong),
        ("idle", c.c_ulong),
        ("event_mask", c.c_ulong),
    ]


class X11IdlePointer:
    def __init__(self, port):
        from Xlib import X, display
        from Xlib.ext import xtest

        self.x11 = c.CDLL("libX11.so.6")
        self.xss = c.CDLL("libXss.so.1")
        self.x11.XOpenDisplay.argtypes = [c.c_char_p]
        self.x11.XOpenDisplay.restype = c.c_void_p
        self.x11.XCloseDisplay.argtypes = [c.c_void_p]
        self.xss.XScreenSaverQueryInfo.argtypes = [
            c.c_void_p,
            c.c_ulong,
            c.POINTER(_IdleInfo),
        ]
        self.xss.XScreenSaverQueryInfo.restype = c.c_int
        self.native = self.x11.XOpenDisplay(None)
        if not self.native:
            raise RuntimeError("Idle display unavailable")
        try:
            self.connection = display.Display()
        except BaseException:
            self.x11.XCloseDisplay(self.native)
            raise
        self.root = self.connection.screen().root
        self.port = int(port)
        self.X, self.xtest = X, xtest

    def snapshot(self):
        window = self.connection.get_input_focus().focus
        if not hasattr(window, "get_wm_class"):
            return None
        classes = window.get_wm_class() or ()
        if not any(
            name.lower() in {"chromium", "google-chrome", "microsoft-edge"}
            for name in classes
        ):
            return None
        owner = window.get_full_property(
            self.connection.intern_atom("_NET_WM_PID"), self.X.AnyPropertyType
        )
        if owner is None or len(owner.value) != 1:
            return None
        command = (
            (Path("/proc") / str(int(owner.value[0])) / "cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode(errors="replace")
        )
        if (
            not re.search(
                rf"(?<!\S)--remote-debugging-port={self.port}(?=\s|$)", command
            )
            or "--type=" in command
        ):
            return None
        geometry = window.get_geometry()
        origin = self.root.translate_coords(window, 0, 0)
        pointer = self.root.query_pointer()
        info = _IdleInfo()
        if not self.xss.XScreenSaverQueryInfo(self.native, self.root.id, c.byref(info)):
            return None
        screen = self.connection.screen()
        # Stay well inside the page, away from window decorations and desktop edges.
        bounds = (
            max(8, origin.x + geometry.width * 0.1),
            max(8, origin.y + geometry.height * 0.25),
            min(screen.width_in_pixels - 8, origin.x + geometry.width * 0.9),
            min(screen.height_in_pixels - 8, origin.y + geometry.height * 0.9),
        )
        return {
            "window": window.id,
            "position": (pointer.root_x, pointer.root_y),
            "buttons": pointer.mask & sum(1 << bit for bit in range(8, 13)),
            "idle_seconds": info.idle / 1000,
            "bounds": bounds,
        }

    def move(self, x, y):
        self.xtest.fake_input(
            self.connection, self.X.MotionNotify, x=round(x), y=round(y)
        )
        self.connection.sync()

    def close(self):
        try:
            self.connection.close()
        finally:
            self.x11.XCloseDisplay(self.native)
