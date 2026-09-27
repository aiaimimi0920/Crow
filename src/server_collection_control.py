"""Native observer API and durable pause/resume ownership."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from .runtime_state import RuntimeState
from .solver_pause_cleanup import PauseSetter

if TYPE_CHECKING:
    from .storage.repository import PropertyRepository


@dataclass(frozen=True)
class CollectionObserver:
    repository: Callable[[], PropertyRepository]

    __all__: ClassVar[list[str]] = [
        "_collection_observer_items_payload",
        "_collection_observer_regions_payload",
        "_collection_observer_item_payload",
        "_collection_observer_reanalysis_payload",
        "_collection_observer_manual_update_payload",
        "_collection_observer_reset_region_links_payload",
    ]

    def _collection_observer_items_payload(
        self,
        query: dict[str, list[str]],
    ) -> dict[str, object]:
        from src.collection_observer_queries import items

        return items(query, repository=self.repository())

    def _collection_observer_regions_payload(
        self,
        query: dict[str, list[str]],
    ) -> dict[str, object]:
        from src.collection_observer_queries import regions

        return regions(query, repository=self.repository())

    def _collection_observer_item_payload(
        self, query: dict[str, list[str]]
    ) -> dict[str, object]:
        from src.collection_observer_queries import item

        return item(query, repository=self.repository())

    def _collection_observer_reanalysis_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        from src.collection_observer_commands import reanalysis

        return reanalysis(payload, repository=self.repository())

    def _collection_observer_manual_update_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        from src.collection_observer_commands import manual_update

        return manual_update(payload, repository=self.repository())

    def _collection_observer_reset_region_links_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        from src.collection_observer_commands import reset_region_links

        return reset_region_links(payload, repository=self.repository())


@dataclass(frozen=True)
class CollectionRuntimeControl:
    runtime: Callable[[], RuntimeState]
    status: Callable[[], dict[str, object]]
    paused: Callable[[], bool]
    set_pause: PauseSetter
    flag_path: Callable[[], str]
    exists: Callable[[str], bool]
    remove: Callable[[str], None]
    clear_challenge: Callable[[], str | None]
    clear_running: Callable[[], None]
    clear_manual: Callable[[], None]
    solver_status: Callable[[], dict[str, object]]
    clock: Callable[[], float]
    label: Callable[[], str]

    __all__: ClassVar[list[str]] = [
        "_collection_runtime_state_label",
        "_collection_observer_runtime_control_payload",
    ]

    def _collection_runtime_state_label(self) -> str:
        try:
            status_payload = self.status()
            runtime_state = str(status_payload.get("runtime_state") or "").strip()
            if runtime_state:
                return runtime_state
        except Exception:  # noqa: BLE001, S110 - optional status failure uses pause state below.
            pass
        if self.paused():
            return "暂停中"
        return "运行中"

    def _collection_observer_runtime_control_payload(
        self, action: str
    ) -> dict[str, object]:
        safe_action = str(action or "").strip().lower()
        if safe_action not in {"pause", "resume"}:
            return {
                "ok": False,
                "error": "action must be pause or resume",
                "action": safe_action,
            }
        if safe_action == "pause":
            self.set_pause(True, "operator")
        else:
            with self.runtime().lock:
                # Keep collection paused until all durable challenge cleanup succeeds.
                self.set_pause(
                    True, self.runtime().control.snapshot().reason or "operator"
                )
                flag_path = self.flag_path()
                if self.exists(flag_path):
                    try:
                        self.remove(flag_path)
                    except Exception as error:  # noqa: BLE001 - preserve the control error envelope.
                        return {
                            "ok": False,
                            "error": f"failed to clear force unlock flag: {error}",
                            "action": safe_action,
                            "paused": self.paused(),
                            "captcha_solver": self.solver_status(),
                        }
                challenge_state_error = self.clear_challenge()
                if challenge_state_error:
                    return {
                        "ok": False,
                        "error": f"failed to clear persisted challenge state: {challenge_state_error}",
                        "action": safe_action,
                        "paused": self.paused(),
                        "captcha_solver": self.solver_status(),
                    }
                self.runtime().recovery.resume(self.clock())
                self.clear_running()
                self.clear_manual()
                self.set_pause(False)
        return {
            "ok": True,
            "action": safe_action,
            "paused": self.paused(),
            "runtime_state": self.label(),
            "captcha_solver": self.solver_status(),
        }
