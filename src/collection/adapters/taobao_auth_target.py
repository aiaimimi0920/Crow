"""Allowlisted, credential-free targets for stage-specific human authentication."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SEED_IDENTITY_QUERY_KEYS = frozenset({"location_code", "st_param", "auction_start_seg", "page"})
DETAIL_PATHS = {
    "sf-item.taobao.com": r"/sf_item/(\d+)\.htm",
    "susong-item.taobao.com": r"/auction/(\d+)\.htm",
}


def auth_target(scope: str, value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in {None, 443} or parsed.fragment):
        raise ValueError("invalid authentication target")
    if scope == "detail":
        pattern = DETAIL_PATHS.get(parsed.hostname)
        match = re.fullmatch(pattern, parsed.path) if pattern else None
        if not match:
            raise ValueError("target does not match authentication stage")
        return f"https://sf-item.taobao.com/sf_item/{match.group(1)}.htm"
    valid = scope == "seed" and parsed.hostname == "sf.taobao.com" and re.fullmatch(r"/list/[\w-]+\.htm", parsed.path)
    if not valid:
        raise ValueError("target does not match authentication stage")
    query = [(key, value) for key, value in parse_qsl(parsed.query)
             if scope == "seed" and key in SEED_IDENTITY_QUERY_KEYS]
    return urlunsplit(("https", parsed.hostname, parsed.path, urlencode(query), ""))


def canonical_auth_target(scope: str, value: str) -> str:
    """Remove a challenge suffix without discarding the collection identity."""
    parsed = urlsplit(value)
    path = re.sub(r"/{2,}", "/", parsed.path).split("/_____tmd_____/", 1)[0]
    return auth_target(scope, urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, "")))


def same_auth_target(scope: str, left: str, right: str) -> bool:
    """Compare collection identity, ignoring query ordering and challenge tokens."""
    try:
        a, b = (urlsplit(auth_target(scope, value)) for value in (left, right))
        return (a.hostname, a.path, sorted(parse_qsl(a.query))) == (b.hostname, b.path, sorted(parse_qsl(b.query)))
    except (ValueError, TypeError, AttributeError):
        return False


def browser_target_matches(scope: str, target_url: str, current_url: str) -> bool:
    """Match challenge routes without losing the collection identity."""
    try:
        return same_auth_target(
            scope, canonical_auth_target(scope, target_url),
            canonical_auth_target(scope, current_url),
        )
    except (ValueError, TypeError, AttributeError):
        return False


def seed_payload_is_authenticated(payload: object, summary: object, *, final_url: str, target_url: str) -> bool:
    """An empty list is valid proof; a blank, malformed or unrelated page is not."""
    return (
        same_auth_target("seed", final_url, target_url)
        and isinstance(payload, dict)
        and isinstance(payload.get("data"), list)
        and isinstance(summary, dict)
        and not any(summary.get(key) for key in ("body_has_challenge", "body_has_login", "body_has_punish"))
    )


def matches_challenge_target(scope: str, target: str, status: dict) -> bool:
    """A healthy default list cannot release a challenge on a regional page."""
    if not status.get("challenge_id"):
        return True
    request = status.get("last_request") or {}
    value = request.get("challenge_target_url") or request.get("target_url") or request.get("url")
    if not isinstance(value, str) or not value:
        return False
    try:
        original = canonical_auth_target(scope, value)
        return same_auth_target(scope, target, original)
    except (ValueError, TypeError):
        return False
