"""Control-plane helpers construct storage only when no repository is supplied."""

import importlib

import pytest
from sqlalchemy import inspect


def test_facade_keeps_named_and_star_repository_exports():
    from src.storage import repository
    from tools import backfill_manual_review_control_plane_to_db as facade

    namespace = {}
    exec(  # noqa: S102 - fixed import statement verifies Python star-import semantics.
        "from tools.backfill_manual_review_control_plane_to_db import *", namespace
    )
    for name in (
        "DatabaseSettings",
        "PropertyRepository",
        "create_repository_from_env",
    ):
        expected = getattr(repository, name)
        assert name in dir(facade)
        assert getattr(facade, name) is expected
        assert namespace[name] is expected
    with pytest.raises(AttributeError, match="missing_repository_export"):
        _ = facade.missing_repository_export


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.manual_review_control_plane_io",
        "tools.backfill_manual_review_control_plane_to_db",
    ],
)
@pytest.mark.parametrize("explicit_url", [False, True])
def test_repository_factory_initializes_explicit_or_environment_database(
    module_name, explicit_url, tmp_path, monkeypatch
):
    module = importlib.import_module(module_name)
    path = tmp_path / "control-plane.sqlite3"
    url = "sqlite:///" + path.as_posix()
    monkeypatch.setenv("FAPAI_DB_ENABLED", "1")
    monkeypatch.setenv("FAPAI_DB_URL", url)
    monkeypatch.setenv("FAPAI_DB_AUTO_CREATE", "1")
    repository = module._build_repo(url if explicit_url else None)
    try:
        assert repository.enabled
        assert path.is_file()
        assert "manual_review_receipt" in inspect(repository.engine).get_table_names()
        supplied = object()
        assert module._build_repo("invalid-url", supplied) is supplied
    finally:
        repository.engine.dispose()
