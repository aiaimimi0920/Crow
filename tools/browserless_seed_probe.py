"""Compatibility facade for the responsibility-split implementation."""

from __future__ import annotations

import functools as _functools
import importlib as _importlib
from pathlib import Path
import sys
import types as _types

try:
    from playwright.sync_api import sync_playwright as _facade_sync_playwright
except ModuleNotFoundError:
    _facade_sync_playwright = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_IMPLEMENTATION_MODULES = (
    "tools.browserless_seed_probe_context",
    "tools.browserless_seed_probe_core",
    "tools.browserless_seed_probe_transport",
    "tools.browserless_seed_probe_navigation",
    "tools.browserless_seed_probe_cookies",
    "tools.browserless_seed_probe_cli",
)
_FACADE_CLASS_NAMES = {}


def _clone_function(function: _types.FunctionType) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__, globals(), function.__name__, function.__defaults__, function.__closure__
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = function.__name__
    return clone


_loaded_modules = [_importlib.import_module(name) for name in _IMPLEMENTATION_MODULES]
_function_pairs: list[tuple[_types.FunctionType, _types.FunctionType]] = []
for _module in _loaded_modules:
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _module.__name__:
            _clone = _clone_function(_value)
            globals()[_name] = _clone
            _function_pairs.append((_value, _clone))
        else:
            if _name in _FACADE_CLASS_NAMES and isinstance(_value, type):
                _value.__module__ = __name__
            globals()[_name] = _value

_function_map = {id(original): clone for original, clone in _function_pairs}
for _original, _clone in _function_pairs:
    if _original.__defaults__:
        _clone.__defaults__ = tuple(_function_map.get(id(value), value) for value in _original.__defaults__)
    if _original.__kwdefaults__:
        _clone.__kwdefaults__ = {
            key: _function_map.get(id(value), value)
            for key, value in _original.__kwdefaults__.items()
        }

# Probe the optional dependency in this facade as well. This matters when the
# file is loaded under an alternate module name with Playwright unavailable.
sync_playwright = _facade_sync_playwright
globals().update(
    _importlib.import_module("tools.browserless_seed_probe_transport").bind_transport(globals())
)


if __name__ == "__main__":
    raise SystemExit(main())
