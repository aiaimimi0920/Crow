"""Legacy alert read/merge/write semantics; no crash-atomicity guarantee."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


class ScreenAlertHost(Protocol):
    AVM_DIR: str
    AVM_ALERTS_PATH: str
    RUNTIME: RuntimeState


@dataclass(frozen=True)
class ScreenAlertStore:
    host: ScreenAlertHost
    __all__: ClassVar[list[str]] = ["write_avm_alerts"]

    def write_avm_alerts(self, alerts: Sequence[Mapping[str, object]]) -> None:
        if not alerts:
            return
        os.makedirs(self.host.AVM_DIR, exist_ok=True)
        with self.host.RUNTIME.file_lock:
            existing: list[Mapping[str, object]] = []
            if os.path.exists(self.host.AVM_ALERTS_PATH):
                try:
                    with open(self.host.AVM_ALERTS_PATH, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, list):
                            existing = cast(list[Mapping[str, object]], loaded)
                except Exception:  # noqa: BLE001 - preserve legacy unreadable-file fallback
                    existing = []
            existing_by_id = {str(alert.get("id")): alert for alert in existing}
            for alert in alerts:
                existing_by_id[str(alert["id"])] = alert
            with open(self.host.AVM_ALERTS_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    list(existing_by_id.values()), f, ensure_ascii=False, indent=2
                )
