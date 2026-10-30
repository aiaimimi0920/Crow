"""Fixed repository frame labels for capture failures across the child boundary."""

from collections import deque
from pathlib import Path

_FILES = frozenset(
    {
        "tools/detail_browser_attached.py",
        "tools/live_smoke_browser.py",
        "tools/live_smoke_cdp.py",
        "tools/live_smoke_list.py",
        "tools/browser_cdp_session.py",
    }
)
_ROOT = Path(__file__).resolve().parents[1]
_LABELS = {str(_ROOT / name): name for name in _FILES}
_FRAME_LIMIT = 8


def safe_capture_frames(value):
    """Accept only bounded known file labels and integer source line numbers."""
    if not isinstance(value, list):
        return []
    frames = []
    for frame in value[:_FRAME_LIMIT]:
        if not isinstance(frame, dict):
            continue
        filename, line = frame.get("file"), frame.get("line")
        if (
            type(filename) is str
            and filename in _FILES
            and type(line) is int
            and 1 <= line <= 1_000_000
        ):
            frames.append({"file": filename, "line": line})
    return frames


def capture_error_frames(error):
    """Do not inspect messages, locals, source, causes or arbitrary filenames."""
    frames = deque(maxlen=_FRAME_LIMIT)
    current = error.__traceback__
    inspected = 0
    while current is not None and inspected < 64:
        label = _LABELS.get(current.tb_frame.f_code.co_filename)
        if label is not None:
            frames.append({"file": label, "line": current.tb_lineno})
        inspected += 1
        current = current.tb_next
    return safe_capture_frames(list(frames))
