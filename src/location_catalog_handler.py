"""Location catalog writes preserve existing names and locked archive updates."""

import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import ClassVar, Protocol, cast

Record = dict[str, object]


class LocationCatalogHandler(Protocol):
    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...


class LocationCatalogRuntime(Protocol):
    file_lock: AbstractContextManager[object]


class LocationCatalogHost(Protocol):
    DATA_DIR: str | Path
    RUNTIME: LocationCatalogRuntime
    logger: Logger

    def _require_control_plane(self, handler: LocationCatalogHandler) -> bool: ...
    def _read_json_body(
        self, handler: LocationCatalogHandler
    ) -> tuple[bool, Record]: ...


@dataclass(frozen=True)
class LocationCatalogHandlers:
    _post_save_locations: Callable[[LocationCatalogHandler], None]
    __all__: ClassVar[list[str]] = ["_post_save_locations"]


def bind_location_catalog(host: LocationCatalogHost) -> LocationCatalogHandlers:
    def _post_save_locations(self: LocationCatalogHandler) -> None:
        from .archive_json_io import read_records, write_records

        if not host._require_control_plane(self):
            return
        accepted, data = host._read_json_body(self)
        if not accepted:
            return
        try:
            new_locations = cast(list[Record], data.get("locations", []))
            loc_file = os.path.join(host.DATA_DIR, "collected_locations.json")
            with host.RUNTIME.file_lock:
                existing_locs = {
                    item["code"]: item["name"] for item in read_records(loc_file)
                }
                updated = False
                for loc in new_locations:
                    code = str(loc.get("code"))
                    name = loc.get("name")
                    if code and name and code not in existing_locs:
                        existing_locs[code] = name
                        updated = True
                if updated:
                    final_list = [
                        {"code": key, "name": value}
                        for key, value in existing_locs.items()
                    ]
                    write_records(loc_file, final_list, indent=2)
                    host.logger.info(
                        "Saved %s locations. Total unique: %s",
                        len(new_locations),
                        len(final_list),
                    )
            self.send_json({"status": "ok", "count": len(new_locations)})
        except Exception as error:
            host.logger.exception("Error saving locations")
            self.send_error_json(
                status=500,
                code="AVM_SAVE_LOCATIONS_FAILED",
                message="行政区划保存失败",
                details={"error": str(error)},
            )

    return LocationCatalogHandlers(_post_save_locations)
