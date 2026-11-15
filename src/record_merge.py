"""Pure fill-missing merge shared by archive and database seed enrichment."""

from copy import deepcopy


def fill_missing(current, incoming):
    result = deepcopy(current)
    for key, value in incoming.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = fill_missing(existing, value)
        elif existing in (None, "", []) and value not in (None, "", []):
            result[key] = deepcopy(value)
    return result
