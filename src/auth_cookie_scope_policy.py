"""Bind detail cookie admission to the current durable challenge owner."""

from collections.abc import Mapping

from src.collection.adapters.taobao_auth_target import canonical_auth_target


def bound_detail_snapshot_target(
    payload: Mapping[str, object], state: Mapping[str, object]
) -> str:
    challenge_id = str(payload.get("challenge_id") or "").strip()
    if not challenge_id or challenge_id != state.get("challenge_id"):
        raise ValueError("detail snapshot does not match the active challenge")
    request = state.get("last_request")
    if not isinstance(request, dict) or request.get("scope") not in (
        None,
        "",
        "detail",
    ):
        raise ValueError("detail challenge request is missing or has a different scope")
    node_id = str(request.get("node_id") or "").strip()
    if not node_id or str(payload.get("node_id") or "").strip() != node_id:
        raise ValueError("detail snapshot belongs to another node")
    endpoint = str(request.get("cdp_endpoint") or "").strip().rstrip("/")
    supplied_endpoint = str(payload.get("cdp_endpoint") or "").strip().rstrip("/")
    if not endpoint or (supplied_endpoint and supplied_endpoint != endpoint):
        raise ValueError("detail snapshot belongs to another CDP session")
    target = (
        request.get("challenge_target_url")
        or request.get("target_url")
        or request.get("url")
    )
    if not isinstance(target, str):
        raise TypeError("detail challenge has no bound target")
    return canonical_auth_target("detail", target)
