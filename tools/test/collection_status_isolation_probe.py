"""Exercise native status over HTTP with a real populated collection repository."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.request import urlopen


def exercise_status(repository, data_root: Path) -> None:
    from src.collection_repository_status import counts_snapshot, data_supply_snapshot
    from src.collection_status_handler import bind_collection_status

    def forbidden(*args, **kwargs):
        raise AssertionError("collection status requested postprocessing")

    host = SimpleNamespace(
        DATA_DIR=data_root,
        DISPATCH_COOLDOWN_SECONDS=60,
        DB_REPOSITORY=repository,
        llm_helper=SimpleNamespace(get_api_metrics=lambda: {"total_calls": 2}),
        _collection_runtime_index=lambda: SimpleNamespace(
            state_snapshot=lambda: ({}, (), {})
        ),
        _collection_api_lightweight_status_enabled=lambda: False,
        _prefer_db_task_reads=lambda: True,
        _db_counts_snapshot=lambda: counts_snapshot(repository),
        _db_pending_task_candidates=lambda **kwargs: [],
        _utc_now=lambda: datetime.now(timezone.utc),
        _as_utc_timestamp=lambda value: value,
        _seed_collection_service=lambda: SimpleNamespace(
            counts_snapshot=repository.search_task_counts
        ),
        _collection_runtime_snapshot=lambda: {
            "paused": False,
            "captcha_solver": {},
            "auth_recovery": {},
            "collection_scopes": {},
        },
        _db_data_supply_snapshot=lambda hours: data_supply_snapshot(
            repository, hours=hours
        ),
        _db_collection_stage_snapshot=forbidden,
        _avm_operator_eval_summary=forbidden,
    )
    status = bind_collection_status(host)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status._get_status(self, None, self.path, {})

        def send_json(self, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_error_json(self, **kwargs):
            self.send_error(kwargs["status"], kwargs["code"])

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/status", timeout=5
            ) as response:
                payload = json.load(response)
            assert payload["total_ids"] == repository.count_listings()
            assert payload["total_ids"] > 0
            assert payload["ai_finalized_count"] > 0
            assert payload["api_total_calls"] == 2
            assert "avm" not in payload
            assert "analysis_stage" not in payload["collection_stage"]
            assert "analysis_blockers" not in payload["collection_stage"]
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()
    print("populated collection status HTTP passed without postprocessing")
