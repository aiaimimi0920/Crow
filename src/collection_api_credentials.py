"""Bind collection credentials and private CA trust to one configured API."""

import ipaddress
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

from src.project_environment import getenv as project_getenv

WORKER_TOKEN_HEADER = "X-FAPAI-Collection-Token"
TOKEN_FILE_ENV = "FAPAI_COLLECTION_WORKER_TOKEN_FILE"
ORIGIN_ENV = "FAPAI_API_BASE_URL"
RECOVERY_TOKEN_FILE_ENV = "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE"
RECOVERY_TOKEN_HEADER = "X-Fapai-Recovery-Token"
CA_FILE_ENV = "FAPAI_API_CA_FILE"
# Preserve legacy exported constants for callers; runtime uses canonical names.
CROW_TOKEN_FILE_ENV = "CROW_COLLECTION_WORKER_TOKEN_FILE"
CROW_ORIGIN_ENV = "CROW_API_BASE_URL"
CROW_RECOVERY_TOKEN_FILE_ENV = "CROW_NAS_AUTH_RECOVERY_TOKEN_FILE"
CROW_CA_FILE_ENV = "CROW_API_CA_FILE"
CREDENTIAL_HEADERS = frozenset(
    {"x-fapai-collection-token", "x-fapai-recovery-token", "x-fapai-control-token"}
)
NODE_AUTH_PATHS = frozenset(
    "/api/collection/auth/" + action
    for action in ("complete", "force_reset", "resume_after_cooldown")
)


def _parse_url(value: str) -> SplitResult:
    if not value or any(ord(char) <= 32 for char in value) or "\\" in value:
        raise ValueError("Invalid collection API URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("Invalid collection API URL")
    _ = parsed.port
    return parsed


def _origin(parsed: SplitResult) -> tuple[str, str, int]:
    port = parsed.port
    return (
        parsed.scheme,
        str(parsed.hostname).lower(),
        port if port is not None else (443 if parsed.scheme == "https" else 80),
    )


def _secure(parsed: SplitResult) -> bool:
    if parsed.scheme == "https" or parsed.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(parsed.hostname)).is_loopback
    except ValueError:
        return False


def _requires_private_ca(parsed: SplitResult) -> bool:
    if parsed.scheme != "https":
        return False
    if parsed.hostname == "localhost":
        return False
    try:
        return not ipaddress.ip_address(str(parsed.hostname)).is_loopback
    except ValueError:
        return True


def _validate_private_ca(parsed: SplitResult) -> None:
    if not _requires_private_ca(parsed):
        return
    ca_file = project_getenv(CROW_CA_FILE_ENV, "").strip()
    if not ca_file:
        raise OSError("Collection API CA file is required for remote HTTPS")
    if not Path(ca_file).is_file():
        raise OSError("Collection API CA file is unavailable")


def secure_api_origin(value: str) -> str:
    """Normalize an API origin before a client reads or transmits credentials."""
    parsed = _parse_url(value)
    if parsed.query or parsed.path.rstrip("/") not in {"", "/api"}:
        raise ValueError("Invalid collection API origin")
    if not _secure(parsed):
        raise ValueError("Collection credentials require HTTPS or a loopback tunnel")
    scheme, host, port = _origin(parsed)
    authority = f"[{host}]" if ":" in host else host
    if port != (443 if scheme == "https" else 80):
        authority += f":{port}"
    return urlunsplit((scheme, authority, "", "", ""))


def worker_token() -> str:
    """Read on demand so rotation needs no process-wide secret cache."""
    path = project_getenv(CROW_TOKEN_FILE_ENV, "").strip()
    if not path:
        return ""
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise OSError("Collection worker credential is unavailable") from error
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", value):
        raise OSError("Collection worker credential is invalid")
    return value


def _bound_target(url: str) -> SplitResult | None:
    configured = project_getenv(CROW_ORIGIN_ENV, "").strip()
    if not configured:
        raise OSError(
            "Collection credential requires CROW_API_BASE_URL (legacy FAPAI_API_BASE_URL is supported)"
        )
    try:
        base, target = _parse_url(configured), _parse_url(url)
    except ValueError as error:
        raise OSError("Invalid collection API destination") from error
    prefix = base.path.rstrip("/")
    if base.query or prefix != "/api":
        raise OSError("Collection API base must use the /api prefix")
    if _origin(base) != _origin(target) or not target.path.startswith(prefix + "/"):
        return None
    if "%" in target.path or any(
        part in {".", ".."} for part in target.path.split("/")
    ):
        raise OSError("Collection API destination must have a canonical path")
    if not _secure(target):
        raise OSError("Collection credentials require HTTPS or a loopback tunnel")
    _validate_private_ca(target)
    return target


def request_headers(
    url: str, supplied: Mapping[str, str] | None = None, *, method: str = "GET"
) -> dict[str, str]:
    """Bind automatic role credentials to canonical routes at the configured origin."""
    headers = dict(supplied or {})
    supplied_credential = any(name.lower() in CREDENTIAL_HEADERS for name in headers)
    if supplied_credential:
        try:
            supplied_target = _parse_url(url)
        except ValueError as error:
            raise OSError("Invalid collection credential destination") from error
        if not _secure(supplied_target):
            raise OSError("Collection credentials require HTTPS or a loopback tunnel")
    worker_configured = bool(project_getenv(CROW_TOKEN_FILE_ENV, "").strip())
    recovery_path = project_getenv(CROW_RECOVERY_TOKEN_FILE_ENV, "").strip()
    if not worker_configured and not recovery_path:
        return headers
    if not worker_configured:
        if any(
            name.lower() in {"x-fapai-control-token", "x-fapai-recovery-token"}
            for name in headers
        ):
            return headers
        if method.upper() != "POST" or urlsplit(url).path not in NODE_AUTH_PATHS:
            return headers
    target = _bound_target(url)
    if target is None:
        return headers
    if supplied_credential:
        return headers
    if target.path in NODE_AUTH_PATHS and method.upper() == "POST":
        if not recovery_path:
            raise OSError("Node authentication requires a recovery credential")
        try:
            token = Path(recovery_path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise OSError("Node recovery credential is unavailable") from error
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", token):
            raise OSError("Node recovery credential is invalid")
        if worker_configured and token == worker_token():
            raise OSError("Node recovery and worker credentials must be distinct")
        headers[RECOVERY_TOKEN_HEADER] = token
    elif worker_configured:
        headers[WORKER_TOKEN_HEADER] = worker_token()
    return headers


def request_verify(url: str) -> str | bool:
    """Use a private CA only for the configured API; never disable TLS verification."""
    if not project_getenv(CROW_ORIGIN_ENV, "").strip():
        return True
    target = _bound_target(url)
    if target is None or target.scheme != "https":
        return True
    ca_file = project_getenv(CROW_CA_FILE_ENV, "").strip()
    if not ca_file:
        raise OSError("Collection API CA file is required for remote HTTPS")
    if not Path(ca_file).is_file():
        raise OSError("Collection API CA file is unavailable")
    return ca_file


def configured_api_base() -> str:
    """Resolve the explicit secure API destination for diagnostic clients."""
    configured = project_getenv(CROW_ORIGIN_ENV, "").strip().rstrip("/")
    if not configured:
        raise OSError(
            "Collection diagnostics require CROW_API_BASE_URL (legacy FAPAI_API_BASE_URL is supported)"
        )
    target = _bound_target(configured + "/status")
    if target is None:
        raise OSError("Collection API base must use the /api prefix")
    return configured
