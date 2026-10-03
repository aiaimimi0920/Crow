"""Exception diagnostics expose fixed categories and bounded stack metadata."""

import errno
import json
from types import FunctionType, SimpleNamespace

import pytest
import requests

from tools.live_smoke_context import CdpEndpointUnavailableError
from tools.safe_exception_diagnostics import (
    safe_cdp_endpoint,
    safe_exception_details,
    safe_exception_text,
    safe_exception_traceback,
)


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("http://127.0.0.1:9223", "http://127.0.0.1:9223"),
        ("http://localhost:9223/", "http://localhost:9223"),
        ("http://container_name:9223", "http://container_name:9223"),
        (
            "https://user:synthetic@cdp.invalid:9443/path?token=synthetic#private",
            "https://cdp.invalid:9443",
        ),
        ("ws://[::1]:9223/devtools/browser/synthetic", "ws://[::1]:9223"),
        ('http://[fe80::1%zone"private]:9223', "<configured CDP endpoint>"),
        ("http://host.invalid:bad", "<configured CDP endpoint>"),
        ("http://host.invalid:0", "<configured CDP endpoint>"),
        ("http://host.invalid\n", "<configured CDP endpoint>"),
        ('http://host".invalid', "<configured CDP endpoint>"),
        ("file:///synthetic", "<configured CDP endpoint>"),
        (None, "<configured CDP endpoint>"),
    ],
)
def test_cdp_diagnostic_endpoint_keeps_only_validated_origin(endpoint, expected):
    assert safe_cdp_endpoint(endpoint) == expected


pytestmark = pytest.mark.security
PRIVATE = "synthetic-private-token"
ENDPOINT = f"https://user:{PRIVATE}@private.invalid/cdp?token={PRIVATE}"


@pytest.mark.parametrize(
    "error,expected",
    [
        (TimeoutError(PRIVATE), "TimeoutError: timeout"),
        (requests.ConnectTimeout(PRIVATE), "TimeoutError: timeout"),
        (requests.ConnectionError(PRIVATE), "ConnectionError: connection_error"),
        (json.JSONDecodeError(PRIVATE, PRIVATE, 0), "JSONDecodeError: invalid_json"),
        (OSError(errno.EACCES, PRIVATE, ENDPOINT), "OSError: io_error errno=EACCES"),
        (ValueError(PRIVATE), "ValueError: invalid_value"),
        (RuntimeError(PRIVATE), "RuntimeError: runtime_error"),
    ],
)
def test_exception_categories_do_not_include_messages(error, expected):
    assert safe_exception_text(error) == expected


def test_cdp_error_keeps_control_attributes_but_has_a_fixed_message():
    cause = TimeoutError(ENDPOINT)
    error = CdpEndpointUnavailableError(ENDPOINT, PRIVATE, cause)
    assert error.cdp_endpoint == ENDPOINT
    assert error.operation == PRIVATE
    assert error.cause is cause
    assert str(error) == "CDP endpoint unavailable"
    assert PRIVATE not in repr(error)


def test_diagnostics_never_stringify_exceptions_or_unknown_status_values():
    class UnprintableError(RuntimeError):
        def __str__(self):
            raise AssertionError("must not stringify exception")

        def __repr__(self):
            raise AssertionError("must not represent exception")

    UnprintableError.__name__ = PRIVATE
    assert (
        safe_exception_text(UnprintableError(PRIVATE)) == "RuntimeError: runtime_error"
    )
    unknown = type(PRIVATE, (Exception,), {})(PRIVATE)
    assert safe_exception_details(unknown) == {
        "type": "Exception",
        "message": "unexpected_error",
    }
    for status in (PRIVATE, UnprintableError(), True, -1, 600, 10**100):
        error = requests.HTTPError(
            PRIVATE, response=SimpleNamespace(status_code=status)
        )
        assert safe_exception_details(error) == {
            "type": "HTTPError",
            "message": "http_error",
        }
    error.response.status_code = 429
    assert safe_exception_text(error) == "HTTPError: http_error status=429"


def test_traceback_drops_paths_source_locals_notes_and_exception_chains():
    def raise_sample():
        private = PRIVATE
        endpoint = ENDPOINT
        try:
            raise ValueError(private)
        except ValueError as cause:
            raise RuntimeError(endpoint) from cause

    sample = FunctionType(
        raise_sample.__code__.replace(
            co_filename=f"/home/{PRIVATE}/source.py", co_firstlineno=1
        ),
        globals(),
    )
    try:
        sample()
    except RuntimeError as error:
        # Python 3.10 has no add_note(), but exceptions support this synthetic
        # attribute; 3.11+ also recognizes it when formatting real tracebacks.
        error.__notes__ = [PRIVATE]
        diagnostic = safe_exception_text(error) + safe_exception_traceback(error)
        assert error.__cause__ is not None
        assert "external:7" in diagnostic
        assert PRIVATE not in diagnostic
        assert "ValueError" not in diagnostic
        assert "/home/" not in diagnostic
        assert "raise " not in diagnostic


def test_traceback_size_is_bounded():
    def recurse(depth):
        if depth:
            return recurse(depth - 1)
        raise ValueError(PRIVATE)

    with pytest.raises(ValueError) as raised:
        recurse(30)
    frames = safe_exception_traceback(raised.value).splitlines()
    assert len(frames) == 21
    assert frames[-1] == "[truncated]"
    assert safe_exception_traceback(ValueError(PRIVATE)) == ""
