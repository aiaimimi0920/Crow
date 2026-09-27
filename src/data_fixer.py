from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from src.data_fixer_app_part_01 import DataFixerAppPart01 as _Part01
from src.data_fixer_app_part_02 import DataFixerAppPart02 as _Part02
from src.data_fixer_app_part_03 import DataFixerAppPart03 as _Part03
from src.data_fixer_app_part_04 import DataFixerAppPart04 as _Part04
from src.data_fixer_app_part_05 import DataFixerAppPart05 as _Part05
from src.data_fixer_runtime import main as main


class DataFixerApp(_Part05, _Part04, _Part03, _Part02, _Part01):
    """Compose native methods with the existing later-part override precedence."""

    save_area = _Part05.save_record
    open_url = _Part03.open_chrome


__all__ = ["DataFixerApp", "main"]


if __name__ == "__main__":
    main()
