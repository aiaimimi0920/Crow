"""Compatibility facade for the split backfill_manual_review_control_plane_to_db tool."""

from __future__ import annotations

import functools as _functools
import importlib as _importlib
from pathlib import Path
import sys
import types as _types

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_IMPLEMENTATION_MODULES = (
    'tools.manual_review_control_plane_context',
    'tools.manual_review_control_plane_io',
    'tools.manual_review_control_plane_integrity',
    'tools.manual_review_control_plane_sync',
    'tools.manual_review_control_plane_status',
    'tools.manual_review_control_plane_preflight',
    'tools.manual_review_control_plane_cli',
)
_FACADE_CLASS_NAMES = {}
_CLONED_CLASS_NAMES = {}


def _clone_function(function: _types.FunctionType, *, qualname: str | None = None) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__, globals(), function.__name__, function.__defaults__, function.__closure__
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = qualname or function.__name__
    return clone


def _clone_class(class_value: type) -> type:
    attributes = {}
    for name, value in class_value.__dict__.items():
        if name in {"__dict__", "__weakref__", "__module__", "__qualname__"}:
            continue
        attributes[name] = (
            _clone_function(value, qualname=f"{class_value.__name__}.{name}")
            if isinstance(value, _types.FunctionType)
            else value
        )
    attributes["__module__"] = __name__
    attributes["__qualname__"] = class_value.__name__
    return type(class_value.__name__, class_value.__bases__, attributes)


_loaded_modules = [_importlib.import_module(name) for name in _IMPLEMENTATION_MODULES]
_function_pairs: list[tuple[_types.FunctionType, _types.FunctionType]] = []
for _module in _loaded_modules:
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _module.__name__:
            _clone = _clone_function(_value)
            globals()[_name] = _clone
            _function_pairs.append((_value, _clone))
        elif _name in _CLONED_CLASS_NAMES and isinstance(_value, type):
            globals()[_name] = _clone_class(_value)
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


_REPOSITORY_EXPORTS = {
    "DatabaseSettings",
    "PropertyRepository",
    "create_repository_from_env",
}


def __getattr__(name: str) -> object:
    if name not in _REPOSITORY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_importlib.import_module("src.storage.repository"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _REPOSITORY_EXPORTS)


__all__ = sorted(
    {name for name in globals() if not name.startswith("_")} | _REPOSITORY_EXPORTS
)


if __name__ == "__main__":
    args = _parse_args()
    if args.mode == "export":
        report = export_manual_review_control_plane_to_json(args.data_root, db_url=args.db_url)
    elif args.mode == "describe-backup":
        report = describe_manual_review_control_plane_backup(args.data_root, db_url=args.db_url)
    elif args.mode == "describe-storage":
        report = describe_manual_review_control_plane_storage(args.data_root, db_url=args.db_url)
    else:
        report = backfill_manual_review_control_plane_to_db(args.data_root, db_url=args.db_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
