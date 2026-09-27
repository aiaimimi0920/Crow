"""Value normalization shared by persisted collection records and their readers."""

import re
from typing import Optional, Union

NumberLike = Union[str, int, float, None]


_MONEY_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def safe_float(value: NumberLike) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        match = _MONEY_NUM_RE.search(s)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None


def parse_money_to_yuan(value: NumberLike) -> Optional[float]:
    """Parse money-like values into yuan.

    Supports: 1230000, "123万", "¥1,230,000", "123.4万元", "1.2亿".
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
        return round(amount, 2) if amount > 0 else None

    s = str(value).strip()
    if not s:
        return None
    s = s.replace("¥", "").replace("￥", "").replace(",", "")

    multiplier = 1.0
    if "亿" in s:
        multiplier = 100000000.0
    elif "万" in s:
        multiplier = 10000.0

    num = safe_float(s)
    if num is None:
        return None
    amount = num * multiplier
    if amount <= 0:
        return None
    return round(amount, 2)


def parse_area_sqm(value: NumberLike) -> Optional[float]:
    """Parse area-like values into square meters."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    s = s.replace("平方米", "").replace("平米", "").replace("㎡", "")

    num = safe_float(s)
    if num is None:
        return None
    if num <= 0:
        return None
    return round(num, 2)
