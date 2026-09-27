from __future__ import annotations

from typing import Any


class _FakeResponse:
    status_code = 200
    text = '{"choices":[{"message":{"content":"```json\\n{\\"ok\\":true}\\n```"}}]}'

    @property
    def ok(self) -> bool:
        return True

    def json(self) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"ok":true}\n```',
                    }
                }
            ]
        }

    def raise_for_status(self) -> None:
        return None


class _FakeUtf8Response:
    status_code = 200
    text = '{"choices":[{"message":{"content":"{\\"å¸\\u0082å\\u009cºè¯\\u0084ä¼\\u00b0ä»·\\":1,\\"æ\\u0098¯å\\u0090¦æ\\u0088\\u0090äº¤\\":true}"}}]}'
    content = (
        b'{"choices":[{"message":{"content":"{\\"'
        + "市场评估价".encode("utf-8")
        + b'\\":1,\\"'
        + "是否成交".encode("utf-8")
        + b'\\":true}"}}]}'
    )

    @property
    def ok(self) -> bool:
        return True

    def json(self) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"å¸\u0082å\u009cºè¯\u0084ä¼°ä»·":1,"æ\u0098¯å\u0090¦æ\u0088\u0090äº¤":true}',
                    }
                }
            ]
        }

    def raise_for_status(self) -> None:
        return None


__all__ = ["_FakeResponse", "_FakeUtf8Response"]
