"""OS pointer adapters. Importing this module never opens an input device."""

import sys
from collections.abc import Callable
from typing import Protocol, cast


class OSPointerBackend(Protocol):
    @property
    def supports_duration(self) -> bool: ...

    def position(self) -> tuple[float, float]: ...

    def move(self, x: float, y: float, duration: float = 0) -> None: ...

    def left_button(self, *, down: bool) -> None: ...


class PyAutoGUIAPI(Protocol):
    def position(self) -> tuple[float, float]: ...

    def moveTo(self, x: float, y: float, duration: float = 0) -> None: ...

    def mouseDown(self) -> None: ...

    def mouseUp(self) -> None: ...


class PyAutoGUIPointerBackend:
    supports_duration = True

    def __init__(self, api: PyAutoGUIAPI) -> None:
        self.api = api

    def position(self) -> tuple[float, float]:
        return self.api.position()

    def move(self, x: float, y: float, duration: float = 0) -> None:
        self.api.moveTo(x, y, duration=duration)

    def left_button(self, *, down: bool) -> None:
        (self.api.mouseDown if down else self.api.mouseUp)()


class Win32API(Protocol):
    def GetCursorPos(self, point: object) -> int: ...

    def SetCursorPos(self, x: int, y: int) -> int: ...

    def GetSystemMetrics(self, index: int) -> int: ...

    def mouse_event(
        self, flags: int, x: int, y: int, data: int, extra: int
    ) -> None: ...


class Win32PointerBackend:
    supports_duration = False

    def __init__(self, api: Win32API | None = None) -> None:
        self._api = api

    @property
    def api(self) -> Win32API:
        if self._api is None:
            if sys.platform != "win32":
                raise OSError("Win32 pointer backend requires Windows")
            import ctypes

            self._api = cast(Win32API, ctypes.windll.user32)
        return self._api

    def position(self) -> tuple[float, float]:
        import ctypes
        from ctypes import wintypes

        point = wintypes.POINT()
        if not self.api.GetCursorPos(ctypes.byref(point)):
            raise OSError("GetCursorPos failed")
        return float(point.x), float(point.y)

    def move(self, x: float, y: float, duration: float = 0) -> None:
        if self.api.SetCursorPos(int(round(x)), int(round(y))):
            return
        # Scheduled processes may need absolute virtual-desktop injection.
        left = int(self.api.GetSystemMetrics(76))
        top = int(self.api.GetSystemMetrics(77))
        width = max(int(self.api.GetSystemMetrics(78)), 1)
        height = max(int(self.api.GetSystemMetrics(79)), 1)
        absolute_x = int(round((x - left) * 65535 / max(width - 1, 1)))
        absolute_y = int(round((y - top) * 65535 / max(height - 1, 1)))
        self.api.mouse_event(
            0x0001 | 0x4000 | 0x8000,
            min(max(absolute_x, 0), 65535),
            min(max(absolute_y, 0), 65535),
            0,
            0,
        )

    def left_button(self, *, down: bool) -> None:
        self.api.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)


class UInputDevice(Protocol):
    def write(self, event_type: int, code: int, value: int) -> None: ...

    def syn(self) -> None: ...


class UInputPointerBackend:
    """The solver owns the device lifetime and cancellable feedback loop."""

    supports_duration = False

    def __init__(
        self,
        position: Callable[[], tuple[float, float]],
        move: Callable[[float, float], None],
        device: Callable[[], tuple[UInputDevice, int, int]],
    ) -> None:
        self._position = position
        self._move = move
        self._device = device

    def position(self) -> tuple[float, float]:
        return self._position()

    def move(self, x: float, y: float, duration: float = 0) -> None:
        self._move(x, y)

    def left_button(self, *, down: bool) -> None:
        handle, event_type, button_code = self._device()
        handle.write(event_type, button_code, 1 if down else 0)
        handle.syn()
