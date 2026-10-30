"""Validate explicit scoped flag provenance without upgrading legacy evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from .collection_control_state import CHALLENGE_SCOPES


def global_manual_pause_active(
    path: str,
    scope_flag_path: Callable[[str], str],
    scope_state_path: Callable[[str], Path],
) -> bool:
    """Unknown, incomplete, stale or changing publications remain global gates."""
    legacy = Path(path)
    try:
        raw = legacy.read_bytes()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        mirror = json.loads(raw)
        if not isinstance(mirror, dict):
            return True
        owner = mirror.get("owner_scope")
        if (
            mirror.get("flag_kind") != "scoped_manual_mirror_v1"
            or not isinstance(owner, str)
            or owner not in CHALLENGE_SCOPES
            or mirror.get("scope") != owner
            or mirror.get("manual_required") is not True
            or type(mirror.get("manual_only")) is not bool
            or not isinstance(mirror.get("publication_id"), str)
            or not mirror["publication_id"].strip()
            or not isinstance(mirror.get("challenge_id"), str)
            or not mirror["challenge_id"].strip()
        ):
            return True
        request = mirror.get("last_request")
        if not isinstance(request, dict) or request.get("scope") != owner:
            return True
        if any(
            not isinstance(request.get(key), str) or not request[key].strip()
            for key in ("node_id", "cdp_endpoint", "target_url")
        ):
            return True
        scoped_path, state_path = Path(scope_flag_path(owner)), scope_state_path(owner)
        scoped_raw, state_raw = scoped_path.read_bytes(), state_path.read_bytes()
        scoped, state = json.loads(scoped_raw), json.loads(state_raw)
        expected = dict(mirror, scope=owner, flag_kind="scoped_manual_v1")
        if json.dumps(scoped, sort_keys=True) != json.dumps(expected, sort_keys=True):
            return True
        if not _state_matches(state, mirror):
            return True
        # File writers outside the owning runtime cannot supply a mixed snapshot.
        return not (
            legacy.read_bytes() == raw
            and scoped_path.read_bytes() == scoped_raw
            and state_path.read_bytes() == state_raw
        )
    except (OSError, ValueError, TypeError, KeyError):
        return True


def _state_matches(state: object, mirror: Mapping[str, object]) -> bool:
    if not isinstance(state, dict):
        return False
    return bool(
        state.get("active") is True
        and state.get("paused") is True
        and state.get("manual_required") is True
        and state.get("manual_only") is mirror["manual_only"]
        and state.get("scope") == mirror["owner_scope"]
        and state.get("challenge_id") == mirror["challenge_id"]
        and state.get("last_request") == mirror["last_request"]
    )
