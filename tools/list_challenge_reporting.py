"""Best-effort challenge notification without losing captured page evidence."""


def report_list_challenge(requester, cdp_endpoint, target_url, *, api_base_url, manual_only):
    try:
        requester(
            cdp_endpoint, target_url, api_base_url=api_base_url,
            manual_only=manual_only,
        )
    except Exception:
        # The caller must still return the challenge page when the API is down.
        pass
