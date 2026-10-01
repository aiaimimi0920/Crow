from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import websocket
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_environment import getenv as project_getenv


DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9"
DEFAULT_PLATFORM_VERSION = "19.0.0"
DEFAULT_READY_PATH = Path("/tmp/fapaifang-browser-identity.ready")


def _chrome_full_version(browser_product: str, explicit: str = "") -> str:
    configured = str(explicit or "").strip()
    if configured:
        return configured
    match = re.search(r"(?:Chrome|Chromium)/(\d+(?:\.\d+){1,3})", str(browser_product or ""))
    return match.group(1) if match else "151.0.0.0"


def _chrome_major_version(user_agent: str, full_version: str) -> str:
    match = re.search(r"(?:Chrome|Chromium|Edg)/(\d+)", str(user_agent or ""))
    if match:
        return match.group(1)
    return str(full_version or "151").split(".", 1)[0]


def _chrome_brand_version_lists(major: str, full_version: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Reproduce Chromium's major-version-seeded UA-CH GREASE list."""
    try:
        seed = max(int(str(major or "").strip()), 0)
    except ValueError:
        seed = 0
    grease_chars = (" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_")
    grease_versions = ("8", "99", "24")
    grease_brand = (
        f"Not{grease_chars[seed % len(grease_chars)]}A"
        f"{grease_chars[(seed + 1) % len(grease_chars)]}Brand"
    )
    grease_version = grease_versions[seed % len(grease_versions)]
    order = (
        (0, 1, 2),
        (0, 2, 1),
        (1, 0, 2),
        (1, 2, 0),
        (2, 0, 1),
        (2, 1, 0),
    )[seed % 6]

    def shuffled(version: str, grease: str) -> list[dict[str, str]]:
        source = (
            {"brand": grease_brand, "version": grease},
            {"brand": "Chromium", "version": version},
            {"brand": "Google Chrome", "version": version},
        )
        result: list[dict[str, str] | None] = [None, None, None]
        for index, target_index in enumerate(order):
            result[target_index] = source[index]
        return [item for item in result if item is not None]

    return (
        shuffled(major, grease_version),
        shuffled(full_version, f"{grease_version}.0.0.0"),
    )


def build_user_agent_override(
    user_agent: str,
    full_version: str,
    *,
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE,
) -> dict[str, Any]:
    major = _chrome_major_version(user_agent, full_version)
    brands, full_version_list = _chrome_brand_version_lists(major, full_version)
    return {
        "userAgent": str(user_agent or "").strip(),
        "acceptLanguage": str(accept_language or DEFAULT_ACCEPT_LANGUAGE).strip(),
        "platform": "Win32",
        "userAgentMetadata": {
            "brands": brands,
            "fullVersionList": full_version_list,
            "fullVersion": full_version,
            "platform": "Windows",
            "platformVersion": DEFAULT_PLATFORM_VERSION,
            "architecture": "x86",
            "model": "",
            "mobile": False,
            "bitness": "64",
            "wow64": False,
        },
    }


def browser_identity_init_script() -> str:
    return r"""
(() => {
  const define = (object, name, value) => {
    try {
      Object.defineProperty(object, name, {
        configurable: true,
        get: () => value,
      });
    } catch (_) {}
  };
  const prototype = globalThis.Navigator && Navigator.prototype;
  if (prototype) {
    define(prototype, 'webdriver', false);
    define(prototype, 'platform', 'Win32');
    define(prototype, 'language', 'zh-CN');
    define(prototype, 'languages', ['zh-CN', 'zh']);
    define(prototype, 'hardwareConcurrency', 12);
    define(prototype, 'deviceMemory', 8);
    define(prototype, 'maxTouchPoints', 10);
  }
  const patchWebGL = (prototype) => {
    const original = prototype && prototype.getParameter;
    if (!original) return;
    try {
      Object.defineProperty(prototype, 'getParameter', {
        configurable: true,
        writable: true,
        value: new Proxy(original, {
          apply(target, thisArg, args) {
            if (args && args[0] === 37445) return 'Google Inc. (Intel)';
            if (args && args[0] === 37446) {
              return 'ANGLE (Intel, Intel(R) HD Graphics 4600 (0x00000412) Direct3D11 vs_5_0 ps_5_0, D3D11)';
            }
            return Reflect.apply(target, thisArg, args);
          },
        }),
      });
    } catch (_) {}
  };
  patchWebGL(globalThis.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchWebGL(globalThis.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
  globalThis.chrome = globalThis.chrome || {runtime: {}};
  try {
    const originalQuery = globalThis.navigator && navigator.permissions && navigator.permissions.query;
    if (originalQuery) {
      navigator.permissions.query = (parameters) => (
        parameters && parameters.name === 'notifications'
          ? Promise.resolve({state: Notification.permission})
          : originalQuery.call(navigator.permissions, parameters)
      );
    }
  } catch (_) {}
})();
""".strip()


class BrowserIdentityController:
    def __init__(
        self,
        *,
        cdp_endpoint: str,
        user_agent: str,
        full_version: str,
        ready_path: Path,
    ) -> None:
        self.cdp_endpoint = str(cdp_endpoint or DEFAULT_CDP_ENDPOINT).rstrip("/")
        self.user_agent = str(user_agent or "").strip()
        self.full_version = str(full_version or "").strip()
        self.ready_path = ready_path
        self.ws: websocket.WebSocket | None = None
        self.message_id = 0
        self.stopping = False
        self.applied_targets = 0
        self.command_responses: dict[int, dict[str, Any]] = {}

    def _send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str = "",
    ) -> int:
        if self.ws is None:
            raise RuntimeError("browser CDP websocket is not connected")
        self.message_id += 1
        payload: dict[str, Any] = {
            "id": self.message_id,
            "method": method,
            "params": params or {},
        }
        if session_id:
            payload["sessionId"] = session_id
        self.ws.send(json.dumps(payload, separators=(",", ":")))
        return self.message_id

    def _send_and_wait(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str = "",
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        command_id = self._send(method, params, session_id=session_id)
        deadline = time.monotonic() + max(float(timeout_seconds), 0.1)
        while time.monotonic() < deadline:
            cached = self.command_responses.pop(command_id, None)
            if cached is not None:
                if cached.get("error"):
                    raise RuntimeError(
                        f"browser identity command failed: {method}: {cached['error']!r}"
                    )
                return cached
            if self.ws is None:
                raise RuntimeError(f"browser identity websocket closed while waiting for {method}")
            try:
                message = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if message.get("id") == command_id:
                if message.get("error"):
                    raise RuntimeError(
                        f"browser identity command failed: {method}: {message['error']!r}"
                    )
                return message
            response_id = message.get("id")
            if isinstance(response_id, int):
                self.command_responses[response_id] = message
                continue
            self._handle_message(message)
        raise TimeoutError(f"browser identity command timed out: {method}")

    def _apply_to_session(self, session_id: str, target_type: str) -> None:
        if target_type == "page":
            source = browser_identity_init_script()
            try:
                self._send_and_wait(
                    "Emulation.setUserAgentOverride",
                    build_user_agent_override(self.user_agent, self.full_version),
                    session_id=session_id,
                )
                self._send_and_wait(
                    "Emulation.setTimezoneOverride",
                    {"timezoneId": "Asia/Shanghai"},
                    session_id=session_id,
                )
                self._send_and_wait(
                    "Emulation.setLocaleOverride",
                    {"locale": "zh-CN"},
                    session_id=session_id,
                )
                self._send_and_wait(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": source},
                    session_id=session_id,
                )
            finally:
                self._send_and_wait("Runtime.runIfWaitingForDebugger", session_id=session_id)
            # Existing tabs may already have a document, while newly created
            # targets receive the init script before their first page script.
            try:
                self._send_and_wait(
                    "Runtime.evaluate",
                    {"expression": source, "returnByValue": True},
                    session_id=session_id,
                )
            except (RuntimeError, TimeoutError) as error:
                print(
                    json.dumps(
                        {
                            "event": "browser_identity_current_document_skipped",
                            "error_type": type(error).__name__,
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
            self.applied_targets += 1
            return
        self._send_and_wait("Runtime.runIfWaitingForDebugger", session_id=session_id)

    def _handle_message(self, message: dict[str, Any]) -> None:
        if message.get("method") != "Target.attachedToTarget":
            return
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        session_id = str(params.get("sessionId") or "").strip()
        target_info = params.get("targetInfo") if isinstance(params.get("targetInfo"), dict) else {}
        if session_id:
            self._apply_to_session(session_id, str(target_info.get("type") or ""))

    def _write_ready(self) -> None:
        self.ready_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.ready_path.with_name(f"{self.ready_path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "ready_at_epoch": time.time(),
                    "platform": "Windows",
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.ready_path)

    def _connect(self) -> None:
        self.command_responses.clear()
        with urlopen(f"{self.cdp_endpoint}/json/version", timeout=5) as response:
            version = json.load(response)
        websocket_url = str(version.get("webSocketDebuggerUrl") or "").strip()
        if not websocket_url:
            raise RuntimeError("browser CDP websocket endpoint is missing")
        if not self.user_agent:
            self.user_agent = str(version.get("User-Agent") or "").strip()
        if not self.full_version:
            self.full_version = _chrome_full_version(str(version.get("Browser") or ""))
        self.ws = websocket.create_connection(
            websocket_url,
            suppress_origin=True,
            timeout=5,
        )
        self.ws.settimeout(1)
        discover_id = self._send("Target.setDiscoverTargets", {"discover": True})
        attach_id = self._send(
            "Target.setAutoAttach",
            {
                "autoAttach": True,
                "waitForDebuggerOnStart": True,
                "flatten": True,
            },
        )
        pending = {discover_id, attach_id}
        deadline = time.monotonic() + 10
        while pending and time.monotonic() < deadline:
            for response_id in tuple(pending):
                cached = self.command_responses.pop(response_id, None)
                if cached is None:
                    continue
                if cached.get("error"):
                    raise RuntimeError(
                        f"browser identity bootstrap command failed: {cached['error']!r}"
                    )
                pending.discard(response_id)
            if not pending:
                break
            message = json.loads(self.ws.recv())
            response_id = message.get("id")
            if response_id in pending:
                if message.get("error"):
                    raise RuntimeError(f"browser identity bootstrap command failed: {message['error']!r}")
                pending.discard(response_id)
            elif isinstance(response_id, int):
                self.command_responses[response_id] = message
            else:
                self._handle_message(message)
        if pending:
            raise TimeoutError("browser identity bootstrap commands timed out")
        self._write_ready()
        print(
            json.dumps(
                {
                    "event": "browser_identity_ready",
                    "platform": "Windows",
                    "applied_targets": self.applied_targets,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    def run(self) -> None:
        self.ready_path.unlink(missing_ok=True)
        while not self.stopping:
            try:
                self._connect()
                while not self.stopping and self.ws is not None:
                    try:
                        message = json.loads(self.ws.recv())
                    except websocket.WebSocketTimeoutException:
                        continue
                    self._handle_message(message)
            except Exception as error:
                if not self.stopping:
                    print(
                        json.dumps(
                            {
                                "event": "browser_identity_reconnect",
                                "error_type": type(error).__name__,
                            },
                            separators=(",", ":"),
                        ),
                        flush=True,
                    )
                    time.sleep(1)
            finally:
                if self.ws is not None:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                    self.ws = None
                self.command_responses.clear()

    def stop(self, *_args: Any) -> None:
        self.stopping = True
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a coherent Windows browser identity before every PC2 CDP page runs."
    )
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--user-agent", default=project_getenv("CROW_BROWSER_USER_AGENT", ""))
    parser.add_argument(
        "--full-version",
        default=project_getenv("CROW_BROWSER_IDENTITY_FULL_VERSION", ""),
    )
    parser.add_argument(
        "--ready-path",
        type=Path,
        default=Path(project_getenv("CROW_BROWSER_IDENTITY_READY_PATH", str(DEFAULT_READY_PATH))),
    )
    args = parser.parse_args()
    controller = BrowserIdentityController(
        cdp_endpoint=args.cdp_endpoint,
        user_agent=args.user_agent,
        full_version=args.full_version,
        ready_path=args.ready_path,
    )
    signal.signal(signal.SIGTERM, controller.stop)
    signal.signal(signal.SIGINT, controller.stop)
    controller.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
