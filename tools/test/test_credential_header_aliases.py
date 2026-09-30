"""Synthetic header fields only; no credentials or network operations."""

from email.message import Message

import pytest

from src.credential_header_aliases import (
    HEADER_PAIRS,
    credential_header,
    credentials_consistent,
)

pytestmark = pytest.mark.security


@pytest.mark.parametrize("new,old", HEADER_PAIRS)
def test_names_are_case_insensitive_and_equal_dual_fields_work(new, old):
    for fields in (
        {new: "synthetic"},
        {old: "synthetic"},
        {new.lower(): "synthetic", old.upper(): "synthetic"},
    ):
        assert credentials_consistent(fields)
        assert credential_header(fields, new) == "synthetic"
        assert credential_header(fields, old) == "synthetic"
        message = Message()
        for key, value in fields.items():
            message[key] = value
        assert credential_header(message, new) == "synthetic"


@pytest.mark.parametrize("new,old", HEADER_PAIRS)
@pytest.mark.parametrize(
    "kind",
    ["duplicate", "duplicate_equal", "comma", "alias", "empty_alias", "case_duplicate"],
)
def test_ambiguous_credentials_fail_closed_across_roles(new, old, kind):
    message = Message()
    message[new] = "synthetic"
    if kind.startswith("duplicate"):
        message[new] = "synthetic" if kind == "duplicate_equal" else "other"
    elif kind == "comma":
        del message[new]
        message[new] = "synthetic,other"
    elif kind == "case_duplicate":
        message[new.lower()] = "other"
    else:
        message[old] = "" if kind == "empty_alias" else "other"
    assert not credentials_consistent(message)
    for pair in HEADER_PAIRS:
        assert credential_header(message, pair[0]) is None
