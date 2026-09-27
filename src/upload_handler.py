"""Bounded binary upload HTTP adapter preserving existing archived evidence."""

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import BinaryIO, ClassVar, Protocol, cast
from urllib.parse import parse_qs, urlparse

UPLOAD_ITEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
UploadTarget = tuple[str, str] | None


class UploadHeaders(Protocol):
    def get(self, name: str) -> str | None: ...


class UploadStream(Protocol):
    def read(self, size: int) -> bytes: ...


class UploadHandler(Protocol):
    path: str
    headers: UploadHeaders
    rfile: UploadStream
    close_connection: bool

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: dict[str, object]
    ) -> None: ...


class UploadPaths(Protocol):
    def basename(self, path: str) -> str: ...


class UploadFilesystem(Protocol):
    path: UploadPaths

    def makedirs(self, path: str, *, exist_ok: bool) -> None: ...


class UploadHost(Protocol):
    DATA_DIR: str | Path
    UPLOAD_MAX_BYTES: int
    _UPLOAD_ITEM_ID_PATTERN: re.Pattern[str]
    os: UploadFilesystem
    logger: Logger

    def _resolve_upload_target(
        self, item_id: object, filename: object
    ) -> UploadTarget: ...


@dataclass(frozen=True)
class UploadHandlers:
    _resolve_upload_target: Callable[[object, object], UploadTarget]
    _post_upload: Callable[[UploadHandler], None]
    _UPLOAD_ITEM_ID_PATTERN: ClassVar[re.Pattern[str]] = UPLOAD_ITEM_ID_PATTERN
    __all__: ClassVar[list[str]] = [
        "_UPLOAD_ITEM_ID_PATTERN",
        "_resolve_upload_target",
        "_post_upload",
    ]


def bind_uploads(host: UploadHost) -> UploadHandlers:
    def _resolve_upload_target(item_id: object, filename: object) -> UploadTarget:
        if not host._UPLOAD_ITEM_ID_PATTERN.fullmatch(str(item_id or "")):
            return None
        base_name = str(filename or "").strip()
        if (
            not base_name
            or base_name in (".", "..")
            or any(character in base_name for character in "/\\:\x00")
            or base_name.endswith((".", " "))
        ):
            return None
        downloads_root = Path(host.DATA_DIR, "downloads").resolve()
        save_dir = downloads_root / str(item_id)
        file_path = (save_dir / base_name).resolve()
        try:
            save_dir.resolve().relative_to(downloads_root)
            file_path.relative_to(save_dir.resolve())
        except ValueError:
            return None
        return str(save_dir), str(file_path)

    def _post_upload(handler: UploadHandler) -> None:
        try:
            params = parse_qs(urlparse(handler.path).query)
            item_id = params.get("id", [""])[0]
            filename = params.get("name", [""])[0]
            try:
                content_length = int(
                    str(handler.headers.get("Content-Length") or "0").strip()
                )
            except ValueError:
                content_length = -1
            if content_length <= 0 or handler.headers.get("Transfer-Encoding"):
                handler.close_connection = True
                handler.send_error_json(
                    status=400,
                    code="AVM_INVALID_UPLOAD_REQUEST",
                    message="Invalid upload framing",
                    details={},
                )
                return
            if content_length > host.UPLOAD_MAX_BYTES:
                handler.close_connection = True
                handler.send_error_json(
                    status=413,
                    code="AVM_REQUEST_BODY_TOO_LARGE",
                    message="请求体超过大小上限",
                    details={
                        "max_bytes": host.UPLOAD_MAX_BYTES,
                        "content_length": content_length,
                    },
                )
                return
            target = (
                host._resolve_upload_target(item_id, filename)
                if item_id and filename
                else None
            )
            if target is None:
                if content_length > 0:
                    handler.rfile.read(content_length)
                handler.send_error_json(
                    status=400,
                    code="AVM_INVALID_UPLOAD_REQUEST",
                    message="上传参数无效",
                    details={"required": ["id", "name"]},
                )
                return
            save_dir, file_path = target
            file_data = handler.rfile.read(content_length)
            if len(file_data) != content_length:
                handler.close_connection = True
                handler.send_error_json(
                    status=400,
                    code="AVM_INVALID_UPLOAD_REQUEST",
                    message="Incomplete upload",
                    details={},
                )
                return
            host.os.makedirs(save_dir, exist_ok=True)
            open_file = cast(
                Callable[[str, str], AbstractContextManager[BinaryIO]],
                getattr(host, "open", open),
            )
            with open_file(file_path, "xb") as stream:
                stream.write(file_data)
            host.logger.info(
                "Saved file: %s (%s bytes)",
                host.os.path.basename(file_path),
                content_length,
            )
            handler.send_json({"status": "saved"})
        except FileExistsError:
            handler.send_error_json(
                status=409,
                code="AVM_UPLOAD_EXISTS",
                message="Existing archive is preserved",
                details={},
            )
        except Exception as error:
            host.logger.exception("Upload failed")
            handler.send_error_json(
                status=500,
                code="AVM_UPLOAD_FAILED",
                message="文件上传失败",
                details={"error": str(error)},
            )

    return UploadHandlers(_resolve_upload_target, _post_upload)
