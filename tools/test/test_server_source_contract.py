from __future__ import annotations

import ast
import inspect
import re
import textwrap
from functools import cache
from pathlib import Path

import pytest

import src.server as server_module
from src.server_routes import RETIRED_GET_ROUTES

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATHS = sorted((REPO_ROOT / "src").glob("server*.py"))
CONTRACT_TEST_PATHS = sorted(
    set((REPO_ROOT / "tools/test").glob("avm_http_contract*.py"))
    | set((REPO_ROOT / "tools/test").rglob("test_*.py"))
    | set((REPO_ROOT / "tests").rglob("test_*.py"))
)
AUTHENTICATED_OBJECT_JSON_ROUTES = {
    "/api/collection/jobs/cancel",
    "/api/collection/auth/recovery/heartbeat",
    "/api/collection/auth/recovery/claim",
    "/api/collection/auth/recovery/pc2_restarting",
    "/api/collection/auth/recovery/result",
    "/api/collection/auth/recovery/snapshot_ready",
}


def _read(paths: list[Path]) -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in paths)


def _function_sources() -> dict[str, str]:
    functions: dict[str, str] = {}
    for path in [*SERVER_PATHS, REPO_ROOT / "src/collection_maintenance_jobs.py"]:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        lines = source.encode("utf-8").splitlines(keepends=True)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = _source_segment(lines, node)
            elif isinstance(node, ast.ClassDef) and node.name == "DataHandler":
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions[child.name] = _source_segment(lines, child)
    # Registered handlers may be native closures outside the legacy server files.
    for name in set(server_module.ROUTES.values()) | {
        "_get_api_not_found",
        "_server_get_fallback",
        "_server_post_fallback",
    }:
        handler = getattr(server_module.DataHandler, name)
        functions[name] = textwrap.dedent(inspect.getsource(handler))
    return functions


def _source_segment(lines: list[bytes], node: ast.AST) -> str:
    start, end = node.lineno - 1, node.end_lineno - 1
    if start == end:
        return lines[start][node.col_offset : node.end_col_offset].decode("utf-8")
    return b"".join(
        [
            lines[start][node.col_offset :],
            *lines[start + 1 : end],
            lines[end][: node.end_col_offset],
        ]
    ).decode("utf-8")


@cache
def _syntax_nodes(source: str) -> tuple[ast.AST, ...]:
    # Cache by source bytes, not symbol names; changed source gets a fresh AST.
    return tuple(ast.walk(ast.parse(source)))


FUNCTION_SOURCES = _function_sources()


@pytest.mark.parametrize(
    "source",
    [
        "def example():\n    value = '中文'\n    return value\n",
        "value = 'π'; result = 'é'\r\n",
        "def outer():\n    def inner():\n        return 1\n    return inner()\n",
    ],
)
def test_indexed_source_segments_match_ast_unicode_offsets(source):
    lines = source.encode("utf-8").splitlines(keepends=True)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.stmt, ast.expr)):
            assert _source_segment(lines, node) == ast.get_source_segment(source, node)


def _delegated_source(name: str, visited: set[str] | None = None) -> str:
    visited = set() if visited is None else visited
    if name in visited:
        return ""
    visited.add(name)
    source = FUNCTION_SOURCES[name]
    nodes = _syntax_nodes(source)
    imports = {
        alias.asname or alias.name
        for node in nodes
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    children = set()
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            children.add(target.attr)
        elif isinstance(target, ast.Name) and target.id in imports:
            children.add(target.id)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            module = getattr(server_module, target.value.id, None)
            source_path = getattr(module, "__file__", None)
            if (
                inspect.ismodule(module)
                and source_path
                and Path(source_path) in SERVER_PATHS
            ):
                children.add(target.attr)
    return "\n".join(
        [
            source,
            *(
                _delegated_source(child, visited)
                for child in sorted(children)
                if child in FUNCTION_SOURCES
            ),
        ]
    )


def _dispatches(method_name: str) -> list[tuple[list[str], str]]:
    method = method_name.removeprefix("do_")
    dispatches: list[tuple[list[str], str]] = []
    for (route_method, path), handler in server_module.ROUTES.items():
        if route_method == method and path.startswith("/api/"):
            dispatches.append(([path], handler))
    return dispatches


def _route_sources(method_name: str) -> list[tuple[list[str], str]]:
    return [
        (routes, _delegated_source(helper_name))
        for routes, helper_name in _dispatches(method_name)
        if helper_name in FUNCTION_SOURCES
    ]


def _catches_value_error(source: str) -> bool:
    for node in _syntax_nodes(source):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        exception_names = {
            child.id for child in ast.walk(node.type) if isinstance(child, ast.Name)
        }
        if "ValueError" in exception_names:
            return True
    return False


def _has_negative_compare(source: str, *, variable: str | None = None) -> bool:
    for node in _syntax_nodes(source):
        if not isinstance(node, ast.Compare) or not any(
            isinstance(op, ast.Lt) for op in node.ops
        ):
            continue
        if variable is not None and not (
            isinstance(node.left, ast.Name) and node.left.id == variable
        ):
            continue
        if any(
            isinstance(item, ast.Constant) and item.value == 0
            for item in node.comparators
        ):
            return True
    return False


def _get_invalid_numeric_query_route_paths() -> list[str]:
    return sorted(
        [
            "/api/analysis/drift_status",
            "/api/analysis/release_gate",
            "/api/analysis/manual_review_control_plane_backup_repairs",
            "/api/analysis/manual_review_control_plane_integrity_history",
            "/api/analysis/manual_review_receipt_operations",
            "/api/avm/archive_detail_replay",
            "/api/avm/drift_status",
            "/api/avm/fetch_missing_detail_archives",
            "/api/avm/recent_detail_replay",
            "/api/avm/recent_gap_audit",
            "/api/avm/release_gate",
            "/api/avm/manual_review_control_plane_backup_repairs",
            "/api/avm/manual_review_control_plane_integrity_history",
            "/api/avm/manual_review_receipt_operations",
            "/api/collection/details/fetch_missing",
            "/api/collection/details/prepare_replay",
        ]
    )


def _get_negative_limit_clamp_route_paths() -> list[str]:
    return sorted(
        [
            "/api/analysis/manual_review_control_plane_backup_repairs",
            "/api/analysis/manual_review_control_plane_integrity_history",
            "/api/analysis/manual_review_receipt_operations",
            "/api/avm/archive_detail_replay",
            "/api/avm/fetch_missing_detail_archives",
            "/api/avm/manual_review_control_plane_backup_repairs",
            "/api/avm/manual_review_control_plane_integrity_history",
            "/api/avm/manual_review_receipt_operations",
            "/api/avm/recent_detail_replay",
            "/api/collection/details/fetch_missing",
            "/api/collection/details/prepare_replay",
        ]
    )


def _get_negative_numeric_query_route_paths() -> list[str]:
    return sorted(
        [
            "/api/analysis/drift_status",
            "/api/analysis/manual_review_control_plane_backup_repairs",
            "/api/analysis/manual_review_control_plane_integrity_history",
            "/api/analysis/manual_review_receipt_operations",
            "/api/analysis/release_gate",
            "/api/avm/archive_detail_replay",
            "/api/avm/drift_status",
            "/api/avm/fetch_missing_detail_archives",
            "/api/avm/manual_review_control_plane_backup_repairs",
            "/api/avm/manual_review_control_plane_integrity_history",
            "/api/avm/manual_review_receipt_operations",
            "/api/avm/recent_detail_replay",
            "/api/avm/recent_gap_audit",
            "/api/avm/release_gate",
            "/api/collection/details/fetch_missing",
            "/api/collection/details/prepare_replay",
        ]
    )


def _source_routes_matching(predicate) -> list[str]:
    routes: set[str] = set()
    for branch_routes, source in _route_sources("do_GET"):
        if predicate(source):
            routes.update(branch_routes)
    return sorted(routes)


def _asserted_error_codes() -> set[str]:
    asserted: set[str] = set()
    for path in CONTRACT_TEST_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                for child in ast.walk(node.test):
                    if (
                        isinstance(child, ast.Constant)
                        and isinstance(child.value, str)
                        and re.fullmatch(r"[A-Z][A-Z0-9_]+", child.value)
                    ):
                        asserted.add(child.value)
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            if function_name not in {
                "assertEqual",
                "_assert_http_error_code",
                "_assert_collection_job_failed",
            }:
                continue
            for argument in node.args:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and re.fullmatch(r"[A-Z][A-Z0-9_]+", argument.value)
                ):
                    asserted.add(argument.value)
    return asserted


def test_server_api_route_literals_are_referenced_by_http_contract_suite():
    routes = sorted(set(re.findall(r"['\"](/api/[^'\"\s]+)['\"]", _read(SERVER_PATHS))))
    suite_text = _read(CONTRACT_TEST_PATHS)
    assert [route for route in routes if route not in suite_text] == []


def test_server_structured_error_codes_are_referenced_by_http_contract_suite():
    codes = sorted(
        set(re.findall(r"code\s*=\s*['\"]([A-Z0-9_]+)['\"]", _read(SERVER_PATHS)))
    )
    suite_text = _read(CONTRACT_TEST_PATHS)
    assert [code for code in codes if code not in suite_text] == []


def test_server_structured_error_codes_are_asserted_by_http_contract_suite():
    codes = set(re.findall(r"code\s*=\s*['\"]([A-Z0-9_]+)['\"]", _read(SERVER_PATHS)))
    assert sorted(codes - _asserted_error_codes()) == []


def test_public_route_json_loads_have_invalid_json_guardrails():
    route_sources = _route_sources("do_POST") + [
        (
            list(server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS),
            _delegated_source("do_DELETE"),
        )
    ]
    missing = [
        routes
        for routes, source in route_sources
        if "json.loads" in source and "AVM_INVALID_JSON" not in source
    ]
    assert missing == []


def test_public_route_object_json_sites_have_non_object_guardrails():
    route_sources = _route_sources("do_POST") + [
        (
            list(server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS),
            _delegated_source("do_DELETE"),
        )
    ]
    missing = [
        routes
        for routes, source in route_sources
        if "json.loads" in source
        and "send_invalid_request_body" not in source
        and "AVM_INVALID_REQUEST_BODY" not in source
    ]
    assert missing == []


def test_live_sweep_object_json_route_inventory_matches_source():
    actual: set[tuple[str, str]] = set()
    for routes, source in _route_sources("do_POST"):
        if "json.loads" in source or "_read_json_body(" in source:
            actual.update((route, "POST") for route in routes)
    if (
        "json.loads" in _delegated_source("do_DELETE")
        or "_read_json_body(" in _delegated_source("do_DELETE")
        or "read_body(" in _delegated_source("do_DELETE")
    ):
        actual.update(
            (route, "DELETE") for route in server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS
        )
    from tools.test.avm_http_contract_base import AVMHttpContractBase

    expected = set(AVMHttpContractBase._object_json_route_methods(None))
    expected.update((route, "POST") for route in AUTHENTICATED_OBJECT_JSON_ROUTES)
    expected.add(("/api/collection/control/start", "POST"))
    expected.update(
        (f"/api/collection/control/{action}", "POST") for action in ("pause", "resume")
    )
    assert sorted(actual) == sorted(expected)


def test_invalid_numeric_query_route_inventory_matches_source():
    expected = sorted(
        set(_get_invalid_numeric_query_route_paths()) - RETIRED_GET_ROUTES.keys()
    )
    assert _source_routes_matching(_catches_value_error) == expected


def test_negative_limit_clamp_route_inventory_matches_source():
    actual = _source_routes_matching(
        lambda source: _has_negative_compare(source, variable="limit")
    )
    expected = sorted(
        set(_get_negative_limit_clamp_route_paths()) - RETIRED_GET_ROUTES.keys()
    )
    assert actual == expected


def test_negative_numeric_query_route_inventory_matches_source():
    expected = sorted(
        set(_get_negative_numeric_query_route_paths()) - RETIRED_GET_ROUTES.keys()
    )
    assert _source_routes_matching(_has_negative_compare) == expected


def test_normalized_numeric_routes_validate_post_json_body():
    expected = (
        set(_get_negative_numeric_query_route_paths()) & RETIRED_GET_ROUTES.keys()
    )
    expected.update(
        {"/api/avm/recent_enrich_maintenance", "/api/collection/details/maintenance"}
    )
    actual = set()
    for routes, source in _route_sources("do_POST"):
        if _has_negative_compare(source) or "nonnegative_integer(" in source:
            assert "_read_json_body(" in source
            assert "payload.get(" in source
            actual.update(routes)
    assert actual == expected


def test_server_has_no_legacy_send_error_calls_in_public_handler():
    assert "self.send_error(" not in _read(SERVER_PATHS)


def _bare_404_owners(source: str) -> set[str]:
    owners: set[str] = set()

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = node.name
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_response"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 404
        ):
            owners.add(owner)
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(ast.parse(source), "<module>")
    return owners


def test_bare_404_inventory_attributes_nested_calls_without_hiding_them():
    source = (
        "def bind():\n"
        "    def callback(handler):\n"
        "        handler.send_response(404)\n"
        "    return callback\n"
    )
    assert _bare_404_owners(source) == {"callback"}
    assert _bare_404_owners(source + "    handler.send_response(404)\n") == {
        "bind",
        "callback",
    }


def test_server_bare_404s_are_only_non_api_fallbacks():
    bare_404_functions = set().union(
        *(_bare_404_owners(source) for source in FUNCTION_SOURCES.values())
    )
    assert bare_404_functions == {
        "do_HEAD",
        "delete_receipt",
        "_server_get_fallback",
        "_server_post_fallback",
    }
    assert "AVM_ENDPOINT_NOT_FOUND" in _delegated_source("do_DELETE")
    assert "AVM_ENDPOINT_NOT_FOUND" in FUNCTION_SOURCES["_server_post_fallback"]
    get_source = FUNCTION_SOURCES["do_GET"]
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "startswith"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "request_path"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "/api/"
        for node in ast.walk(ast.parse(get_source))
    )
    assert "self._server_get_fallback" in get_source


def test_facade_defined_functions_use_server_facade_globals():
    mismatches = [
        name
        for name, value in vars(server_module).items()
        if inspect.isfunction(value)
        and value.__module__ == "src.server"
        and value.__globals__ is not vars(server_module)
    ]
    assert mismatches == []


def test_registered_routes_have_callable_data_handler_methods():
    missing = [
        (method, path, handler)
        for (method, path), handler in server_module.ROUTES.items()
        if not callable(getattr(server_module.DataHandler, handler, None))
    ]
    assert missing == []
