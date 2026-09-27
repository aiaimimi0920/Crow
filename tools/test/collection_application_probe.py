"""Full collection startup probe; all mutations stay in the supplied test root."""

from __future__ import annotations

import importlib.abc
import json
import os
import sys
import threading
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace


class RejectPostprocessing(importlib.abc.MetaPathFinder):
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            "src.avm",
            "src.avm_config",
            "src.server",
            "src.server_context",
            "src.analysis_read_handlers",
            "src.manual_review_status",
            "src.collection_stage_status",
        } or fullname.startswith(
            (
                "src.avm.",
                "tools.analysis_",
                "tools.run_recent_enrich_maintenance",
                "tools.apply_avm_",
            )
        ):
            self.attempts.append(fullname)
            raise ImportError("postprocessing intentionally unavailable: " + fullname)


def run(root: Path, source: str) -> None:
    os.environ["FAPAI_DATA_ROOT"] = str(root)
    os.environ["FAPAI_SOLVER_STATE_DIR"] = str(root)
    os.environ["FAPAI_NAS_AUTH_RECOVERY_STATE_PATH"] = str(root / "recovery.json")
    os.environ["FAPAI_NAS_AUTH_RECOVERY_ENABLED"] = "1"
    os.environ["FAPAI_CONTROL_PLANE_TOKEN"] = "isolated-operator"
    token = "isolated-collection-worker-" * 2
    token_file = root / "worker.token"
    token_file.write_text(token, encoding="utf-8")
    os.environ["FAPAI_COLLECTION_WORKER_TOKEN_FILE"] = str(token_file)
    guard = RejectPostprocessing()
    sys.meta_path.insert(0, guard)
    from src.collection.adapters.generic_product import GenericProductAdapter
    from src.collection.adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
    from src.collection_application import create_application
    from src.storage import CollectionRepository, DatabaseSettings

    adapter = (
        TaobaoJudicialAuctionAdapter()
        if source == "taobao_sf"
        else GenericProductAdapter(source_platform=source)
    )
    repository = CollectionRepository(
        DatabaseSettings(
            url=f"sqlite:///{(root / 'collection.sqlite3').as_posix()}",
            enabled=True,
            auto_create=True,
        ),
        adapter=adapter,
    )
    app = create_application(data_root=root, repository=repository, adapter=adapter)
    entered, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def extract(content, *, item_id=None):
        calls.append(item_id)
        entered.set()
        if not release.wait(10):
            raise TimeoutError("test extraction was not released")
        return json.dumps(
            {
                "title": "Archived fixture",
                "status": "done",
                "建筑面积": 80,
                "seller_note": "preserved evidence",
            }
        )

    def reject_source(*_args, **_kwargs):
        raise AssertionError("wrong source extractor selected")

    app.host.llm_helper = SimpleNamespace(
        extract_auction_data=extract if source == "taobao_sf" else reject_source,
        extract_product_data=reject_source if source == "taobao_sf" else extract,
        extract_avm_risk_features=(lambda *_args, **_kwargs: {})
        if source == "taobao_sf"
        else reject_source,
        log_prediction_event=lambda **_event: None,
        get_api_metrics=lambda: {"total_calls": len(calls)},
    )
    # Restrict only the test's discovery catalog; the production startup and workers run.
    jobs = root / "jobs"
    jobs.mkdir()
    app.host.JOBS_DIR = str(jobs)
    snapshot_pending = threading.Event()
    write_snapshot_state = app.host._set_auth_cookie_snapshot_state

    def set_snapshot_state(**updates):
        result = write_snapshot_state(**updates)
        if updates.get("status") == "pending" and updates.get("attempts") == 1:
            snapshot_pending.set()
        return result

    app.host._set_auth_cookie_snapshot_state = set_snapshot_state
    app.host._refresh_auth_cookie_snapshot = lambda _payload: {
        "refreshed": False,
        "reason": "isolated_retry",
    }
    app.host._auth_cookie_snapshot_retry_attempts = lambda: 3
    app.host._auth_cookie_snapshot_retry_backoff_seconds = lambda: 120.0
    closed = threading.Event()
    close_errors: list[BaseException] = []

    def close_application():
        try:
            app.close()
        except BaseException as error:  # noqa: BLE001 - surface thread failures to the probe.
            close_errors.append(error)
        finally:
            closed.set()

    closer = threading.Thread(target=close_application)
    httpd = app.http_server(("127.0.0.1", 0))
    listener = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}
    )

    def request(method: str, path: str, payload=None, *, authorized=True):
        connection = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        try:
            headers = {"Content-Type": "application/json"}
            if authorized:
                headers.update(
                    {
                        "X-FAPAI-Collection-Token": token,
                        "X-FAPAI-Control-Token": "isolated-operator",
                    }
                )
            connection.request(
                method,
                path,
                body=json.dumps(payload) if payload is not None else None,
                headers=headers,
            )
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()

    try:
        app.start()
        app.start()
        assert len(app.threads) == 4 and all(
            thread.is_alive() for thread in app.threads
        )
        listener.start()
        assert (
            request(
                "POST", "/api/collection/seeds/batch", {"items": []}, authorized=False
            )[0]
            == 403
        )
        seed = {
            "id": "123",
            "title": "Seed fixture",
            "status": "done",
            "url": "https://sf-item.taobao.com/sf_item/123.htm"
            if source == "taobao_sf"
            else "https://catalog.example/items/123",
        }
        status, saved = request(
            "POST", "/api/collection/seeds/batch", {"items": [seed]}
        )
        assert status == 200 and saved["new"] == 1, (status, saved)
        item_id = adapter.item_id(seed)
        assert repository.get_flat_item(item_id)["source_platform"] == source
        status, state = request("GET", "/api/status")
        assert status == 200 and state["total_ids"] == 1, (status, state)
        assert "avm" not in state and "analysis_stage" not in state["collection_stage"]
        assert request("GET", "/api/collection/overview")[0] == 200
        assert request("GET", "/api/avm/health")[0] == 404
        evidence = "<html><body>Fixture evidence, size 80 square meters.</body></html>"
        status, accepted = request(
            "POST", "/api/collection/details/html", {"id": item_id, "html": evidence}
        )
        assert status == 200 and accepted["status"] == "queued", (status, accepted)
        assert entered.wait(5), "production detail worker did not execute"
        assert not repository.get_flat_item(item_id)["is_processed"]
        app.host._schedule_auth_cookie_snapshot_refresh(
            {}, "isolated-completion", finalize_auth=True
        )
        assert snapshot_pending.wait(5), "cookie retry did not reach its backoff"
        closer.start()
        assert app.stop_event.wait(5)
        assert not closed.is_set(), "shutdown did not wait for active detail work"
        status, stopping = request(
            "POST", "/api/collection/seeds/batch", {"items": [seed]}
        )
        assert status == 503 and stopping["error"]["code"] == "COLLECTION_STOPPING"
        httpd.shutdown()
        listener.join(timeout=5)
        httpd.server_close()
        release.set()
        closer.join(timeout=10)
        assert closed.is_set() and not close_errors, close_errors
        snapshot_state = app.host._auth_cookie_snapshot_runtime_state()
        assert snapshot_state.active_thread() is None
        snapshot = snapshot_state.snapshot()
        assert snapshot["result"]["reason"] == "application_stopping", snapshot
        assert snapshot["attempts"] == 1 and not snapshot["auth_state_confirmed"]
        try:
            app.host._schedule_auth_cookie_snapshot_refresh({}, "late-completion")
        except RuntimeError:
            pass
        else:
            raise AssertionError("closed application accepted a cookie refresh")
        assert not listener.is_alive() and all(
            not thread.is_alive() for thread in app.threads
        )
        assert not app.host.RUNTIME.processing.snapshot()
        record = repository.get_flat_item(item_id)
        assert record["is_processed"] is True, record
        assert record["source_item_id"] == "123" and record["source_platform"] == source
        archive = root / record["detail_archive_path"]
        assert archive.read_text(encoding="utf-8") == evidence
        assert not (root / "html" / f"item-{item_id}.html").exists()
        assert calls == [item_id], calls
        assert not guard.attempts, guard.attempts
        assert "src.avm" not in sys.modules and "src.server_context" not in sys.modules
        print(
            "collection API: seed, HTML, storage, workers stopped; postprocessing absent"
        )
    finally:
        release.set()
        if listener.is_alive():
            httpd.shutdown()
            listener.join(timeout=5)
        httpd.server_close()
        if closer.is_alive():
            closer.join(timeout=10)
        app.close()
        repository.engine.dispose()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    run(Path(sys.argv[1]), sys.argv[2])
