"""Collection archive naming and raw artifact publication with live dependencies."""

import datetime as datetime_module
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol


class ArchiveDates(Protocol):
    datetime: type[datetime_module.datetime]
    date: type[datetime_module.date]


class ArchivePathOperations(Protocol):
    join: Callable[..., str]
    exists: Callable[[str | Path], bool]
    relpath: Callable[[str, str], str]


class ArchiveFilesystem(Protocol):
    path: ArchivePathOperations
    makedirs: Callable[[str], None]


class DetailArtifacts(Protocol):
    def __call__(
        self,
        *,
        data_root: str,
        html_content: str,
        item_id: object,
        auction_date: object = None,
        source_url: str | None = None,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class CollectionArchivePaths:
    data_root: Callable[[], str]
    dates: Callable[[], ArchiveDates]
    filesystem: Callable[[], ArchiveFilesystem]
    dump: Callable[..., None]
    list_path: Callable[[object, str], str]
    detail_path: Callable[[str, object, object, str], Path]
    extract: DetailArtifacts

    __all__: ClassVar[list[str]] = [
        "get_data_path",
        "get_detail_archive_path",
        "get_list_payload_archive_path",
        "archive_list_payload",
        "_extract_detail_artifacts",
    ]

    def _date(self, value: object) -> datetime_module.date:
        dates = self.dates()
        if isinstance(value, str):
            try:
                return dates.datetime.strptime(value[:10], "%Y-%m-%d")
            except ValueError:
                return dates.datetime.now()
        if isinstance(value, (dates.date, dates.datetime)):
            return value
        return dates.datetime.now()

    def get_data_path(self, date_str_or_obj: object) -> str:
        dt = self._date(date_str_or_obj)
        fs = self.filesystem()
        archive_dir = fs.path.join(self.data_root(), "archive", dt.strftime("%Y"))
        if not fs.path.exists(archive_dir):
            fs.makedirs(archive_dir)
        return fs.path.join(archive_dir, f"{dt.strftime('%Y-%m-%d')}.json")

    def get_detail_archive_path(
        self, date_str_or_obj: object, item_id: object, extension: str = ".html"
    ) -> str:
        return str(
            self.detail_path(self.data_root(), date_str_or_obj, item_id, extension)
        )

    def get_list_payload_archive_path(
        self, date_str_or_obj: object = None, suffix: str = ".json"
    ) -> str:
        dt = self._date(date_str_or_obj)
        fs = self.filesystem()
        archive_dir = fs.path.join(
            self.data_root(),
            "list_payload_archive",
            dt.strftime("%Y"),
            dt.strftime("%Y-%m-%d"),
        )
        if not fs.path.exists(archive_dir):
            fs.makedirs(archive_dir)
        timestamp = dt.strftime("%Y%m%d-%H%M%S-%f")
        normalized_suffix = suffix if str(suffix).startswith(".") else f".{suffix}"
        return fs.path.join(archive_dir, f"list-{timestamp}{normalized_suffix}")

    def archive_list_payload(
        self, raw_payload: object, captured_at: object = None
    ) -> str | None:
        if raw_payload in (None, "", []):
            return None
        payload_path = self.list_path(captured_at, ".json")
        with open(payload_path, "w", encoding="utf-8") as handle:
            self.dump(raw_payload, handle, ensure_ascii=False, indent=2)
        return (
            self.filesystem()
            .path.relpath(payload_path, self.data_root())
            .replace("\\", "/")
        )

    def _extract_detail_artifacts(
        self,
        html_content: str,
        item_id: object,
        auction_date: object = None,
        source_url: str | None = None,
    ) -> dict[str, object]:
        return self.extract(
            data_root=self.data_root(),
            html_content=html_content,
            item_id=item_id,
            auction_date=auction_date,
            source_url=source_url,
        )
