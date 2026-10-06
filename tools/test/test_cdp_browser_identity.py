from __future__ import annotations

import json
from pathlib import Path

from tools import cdp_browser_identity


PC1_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


def test_user_agent_override_keeps_windows_ua_and_client_hints_coherent() -> None:
    payload = cdp_browser_identity.build_user_agent_override(
        PC1_USER_AGENT,
        "151.0.7922.174",
    )

    assert payload["userAgent"] == PC1_USER_AGENT
    assert payload["platform"] == "Win32"
    assert payload["acceptLanguage"] == "zh-CN,zh"
    metadata = payload["userAgentMetadata"]
    assert metadata["platform"] == "Windows"
    assert metadata["platformVersion"] == "19.0.0"
    assert metadata["architecture"] == "x86"
    assert metadata["bitness"] == "64"
    assert metadata["mobile"] is False
    assert metadata["fullVersion"] == "151.0.7922.174"
    assert metadata["brands"] == [
        {"brand": "Not=A?Brand", "version": "99"},
        {"brand": "Google Chrome", "version": "151"},
        {"brand": "Chromium", "version": "151"},
    ]


def test_chrome_152_client_hint_brands_match_native_chrome_order() -> None:
    payload = cdp_browser_identity.build_user_agent_override(
        PC1_USER_AGENT.replace("Chrome/151.0.0.0", "Chrome/152.0.0.0"),
        "152.0.7977.64",
    )

    metadata = payload["userAgentMetadata"]
    assert metadata["brands"] == [
        {"brand": "Chromium", "version": "152"},
        {"brand": "Not?A_Brand", "version": "24"},
        {"brand": "Google Chrome", "version": "152"},
    ]
    assert metadata["fullVersionList"] == [
        {"brand": "Chromium", "version": "152.0.7977.64"},
        {"brand": "Not?A_Brand", "version": "24.0.0.0"},
        {"brand": "Google Chrome", "version": "152.0.7977.64"},
    ]


def test_identity_init_script_matches_pc1_navigator_signals() -> None:
    source = cdp_browser_identity.browser_identity_init_script()

    for expected in (
        "'platform', 'Win32'",
        "'language', 'zh-CN'",
        "'languages', ['zh-CN', 'zh']",
        "'hardwareConcurrency', 12",
        "'deviceMemory', 8",
        "'maxTouchPoints', 10",
        "'webdriver', false",
        "Google Inc. (Intel)",
        "Direct3D11 vs_5_0 ps_5_0",
        "globalThis.chrome = globalThis.chrome || {runtime: {}}",
    ):
        assert expected in source
    assert "define(prototype, 'plugins'" not in source


def test_attached_page_is_hardened_before_runtime_resumes(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []

    class _WebSocket:
        response_ids: list[int] = []

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            sent.append(message)
            self.response_ids.append(message["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.response_ids.pop(0), "result": {}})

    controller = cdp_browser_identity.BrowserIdentityController(
        cdp_endpoint="http://127.0.0.1:9223",
        user_agent=PC1_USER_AGENT,
        full_version="151.0.7922.174",
        ready_path=tmp_path / "ready.json",
    )
    controller.ws = _WebSocket()  # type: ignore[assignment]

    controller._handle_message(
        {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": "session-1",
                "targetInfo": {"type": "page"},
            },
        }
    )

    assert [message["method"] for message in sent] == [
        "Target.setAutoAttach",
        "Emulation.setUserAgentOverride",
        "Emulation.setTimezoneOverride",
        "Emulation.setLocaleOverride",
        "Page.enable",
        "Page.addScriptToEvaluateOnNewDocument",
        "Runtime.runIfWaitingForDebugger",
        "Runtime.evaluate",
    ]
    assert all(message["sessionId"] == "session-1" for message in sent)
    assert sent[2]["params"] == {"timezoneId": "Asia/Shanghai"}
    assert sent[3]["params"] == {"locale": "zh-CN"}


def test_non_page_target_is_only_resumed(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []

    class _WebSocket:
        response_ids: list[int] = []

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            sent.append(message)
            self.response_ids.append(message["id"])

        def recv(self) -> str:
            return json.dumps({"id": self.response_ids.pop(0), "result": {}})

    controller = cdp_browser_identity.BrowserIdentityController(
        cdp_endpoint="http://127.0.0.1:9223",
        user_agent=PC1_USER_AGENT,
        full_version="151.0.7922.174",
        ready_path=tmp_path / "ready.json",
    )
    controller.ws = _WebSocket()  # type: ignore[assignment]

    controller._handle_message(
        {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": "session-worker",
                "targetInfo": {"type": "service_worker"},
            },
        }
    )

    assert [message["method"] for message in sent] == ["Runtime.runIfWaitingForDebugger"]


def test_attached_page_confirms_init_script_before_resuming(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []

    class _WebSocket:
        response_ids: list[int] = []

        def send(self, payload: str) -> None:
            message = json.loads(payload)
            sent.append(message)
            self.response_ids.append(message["id"])

        def recv(self) -> str:
            command_id = self.response_ids.pop(0)
            return json.dumps({"id": command_id, "result": {}})

    controller = cdp_browser_identity.BrowserIdentityController(
        cdp_endpoint="http://127.0.0.1:9223",
        user_agent=PC1_USER_AGENT,
        full_version="151.0.7922.174",
        ready_path=tmp_path / "ready.json",
    )
    controller.ws = _WebSocket()  # type: ignore[assignment]

    controller._apply_to_session("session-verified", "page")

    methods = [message["method"] for message in sent]
    assert methods.index("Page.addScriptToEvaluateOnNewDocument") < methods.index(
        "Runtime.runIfWaitingForDebugger"
    )
    assert methods[-1] == "Runtime.evaluate"


def test_command_wait_preserves_unrelated_bootstrap_response(tmp_path: Path) -> None:
    sent: list[dict[str, object]] = []

    class _WebSocket:
        replies = [
            json.dumps({"id": 91, "result": {"bootstrap": True}}),
            json.dumps({"id": 1, "result": {"command": True}}),
        ]

        def send(self, payload: str) -> None:
            sent.append(json.loads(payload))

        def recv(self) -> str:
            return self.replies.pop(0)

    controller = cdp_browser_identity.BrowserIdentityController(
        cdp_endpoint="http://127.0.0.1:9223",
        user_agent=PC1_USER_AGENT,
        full_version="151.0.7922.174",
        ready_path=tmp_path / "ready.json",
    )
    controller.ws = _WebSocket()  # type: ignore[assignment]

    response = controller._send_and_wait("Runtime.enable")

    assert response["id"] == 1
    assert controller.command_responses[91]["result"] == {"bootstrap": True}
    assert sent[0]["method"] == "Runtime.enable"
