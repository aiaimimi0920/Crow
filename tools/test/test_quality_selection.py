"""Explicit collector selection retains node precision and rejects empty matches."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.quality_selection import QualitySelection


class Item:
    def __init__(self, nodeid):
        self.nodeid = nodeid


@pytest.mark.parametrize(
    "selector,expected",
    [
        ("test_one.py", [0, 1, 2]),
        ("test_one.py::test_a", [0, 1]),
        ("test_one.py::test_a[x]", [0]),
        ("test_one.py::Case", [2]),
    ],
)
def test_selection_preserves_file_function_parameter_and_class(
    tmp_path, selector, expected
):
    items = [
        Item(name)
        for name in (
            "test_one.py::test_a[x]",
            "test_one.py::test_a[y]",
            "test_one.py::Case::test_nested",
            "test_two.py::test_other",
        )
    ]
    originals = list(items)
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    QualitySelection(tmp_path, [selector]).pytest_collection_modifyitems(config, items)
    assert items == [originals[index] for index in expected]
    config.hook.pytest_deselected.assert_called_once_with(
        items=[item for item in originals if item not in items]
    )


def test_missing_selector_fails_even_when_another_selector_matches(tmp_path):
    selection = QualitySelection(tmp_path, ["test_one.py", "test_one.py::test_missing"])
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    with pytest.raises(pytest.UsageError, match="test_one.py::test_missing"):
        selection.pytest_collection_modifyitems(
            config, [Item("test_one.py::test_present")]
        )


def test_ignore_unselected_files_and_directories_before_collection(tmp_path):
    selection = QualitySelection(tmp_path, ["tools/test/manual_case.py::test_one"])
    assert not selection.pytest_ignore_collect(tmp_path / "tools")
    assert not selection.pytest_ignore_collect(tmp_path / "tools/test")
    assert not selection.pytest_ignore_collect(tmp_path / "tools/test/manual_case.py")
    assert selection.pytest_ignore_collect(tmp_path / "tools/test/test_unselected.py")
    assert selection.pytest_ignore_collect(tmp_path / "tools/test/unselected_directory")


def test_selection_keeps_manifest_order_and_does_not_duplicate_overlap(tmp_path):
    first, second = Item("test_one.py::test_first"), Item("test_one.py::test_second")
    items = [first, second]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    QualitySelection(
        tmp_path, ["test_one.py::test_second", "test_one.py"]
    ).pytest_collection_modifyitems(config, items)
    assert items == [second, first]
    config.hook.pytest_deselected.assert_not_called()
