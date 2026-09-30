"""Resolve credential header spellings without hiding duplicate credentials."""

from collections.abc import Mapping

HEADER_PAIRS = (
    ("X-Crow-Control-Token", "X-FAPAI-Control-Token"),
    ("X-Crow-Recovery-Token", "X-Fapai-Recovery-Token"),
    ("X-Crow-Collection-Token", "X-FAPAI-Collection-Token"),
)
CREDENTIAL_HEADERS = frozenset(name.lower() for pair in HEADER_PAIRS for name in pair)


def _values(headers: object, name: str) -> list[str]:
    # HTTPMessage.get_all retains duplicates; mapping fixtures retain case variants.
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        return [str(value) for value in (get_all(name) or [])]
    if isinstance(headers, Mapping):
        return [
            str(value)
            for key, value in headers.items()
            if str(key).lower() == name.lower()
        ]
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    return [] if value is None else [str(value)]


def _pair(headers: object, names: tuple[str, str]) -> tuple[bool, str | None]:
    groups = [_values(headers, name) for name in names]
    # A repeated field or comma-merged token is ambiguous even if its first value matches.
    if any(
        len(values) > 1 or any("," in value for value in values) for values in groups
    ):
        return False, None
    values = [values[0] for values in groups if values]
    if len(values) == 2 and values[0] != values[1]:
        return False, None
    return True, values[0] if values else None


def credentials_consistent(headers: object) -> bool:
    return all(_pair(headers, pair)[0] for pair in HEADER_PAIRS)


def credential_header(headers: object, name: str) -> str | None:
    """Return no credential if any role contains ambiguous duplicate/alias fields."""
    if not credentials_consistent(headers):
        return None
    for pair in HEADER_PAIRS:
        if name.lower() in {value.lower() for value in pair}:
            return _pair(headers, pair)[1]
    raise ValueError("Unknown credential header name")
