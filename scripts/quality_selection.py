"""Collect an explicit suite once without importing unselected sibling modules."""

import json
import os
from pathlib import Path

import pytest


class QualitySelection:
    def __init__(self, root: Path, selectors: list[str]):
        self.selectors = selectors
        self.files = {root / selector.split("::", 1)[0] for selector in selectors}
        self.parents = {parent for path in self.files for parent in path.parents}

    def pytest_ignore_collect(self, collection_path: Path) -> bool:
        return collection_path not in self.files and collection_path not in self.parents

    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        selected = []
        retained = set()
        missing = []
        for selector in self.selectors:
            matched = [
                item
                for item in items
                if item.nodeid == selector
                or item.nodeid.startswith(selector + "::")
                or item.nodeid.startswith(selector + "[")
            ]
            if not matched:
                missing.append(selector)
            for item in matched:
                if item not in retained:
                    selected.append(item)
                    retained.add(item)
        if missing:
            raise pytest.UsageError(
                "Quality suite selectors not found: " + ", ".join(missing)
            )
        deselected = [item for item in items if item not in retained]
        items[:] = selected
        if deselected:
            config.hook.pytest_deselected(items=deselected)


def pytest_configure(config: pytest.Config) -> None:
    raw = json.loads(os.environ["CROW_QUALITY_SELECTION"])
    if (
        not isinstance(raw, list)
        or not raw
        or not all(isinstance(item, str) for item in raw)
    ):
        raise pytest.UsageError(
            "Quality suite selection must be a nonempty string list"
        )
    config.pluginmanager.register(
        QualitySelection(config.rootpath, raw), "crow-quality-selection"
    )
