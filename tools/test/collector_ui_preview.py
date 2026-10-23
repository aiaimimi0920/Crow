"""Loopback-only built UI preview; all API actions use disposable fixtures."""

import argparse
import json
import os
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from collector_ui_fixtures import REGIONS, item_detail, item_list, overview

DIST = Path(os.environ["CROW_TEST_FRONTEND_DIST"]).resolve() if os.environ.get("CROW_TEST_FRONTEND_DIST") else Path(__file__).resolve().parents[2] / "collector-desktop" / "dist"


class PreviewServer(ThreadingHTTPServer):
    def __init__(self, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.scenario = "normal"
        self.runtime = "运行中"
        self.delay = 0
        self.events = []
        self.updates = {}
        self.challenge = True
        self.restart = {"available": True, "request": None}
        self.growth = [0, 0, 0]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, *args):
        pass

    def respond(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/__preview/state":
            return self.respond({"scenario": self.server.scenario, "events": self.server.events})
        if not path.startswith("/api/"):
            return super().do_GET()
        time.sleep(self.server.delay)
        if self.server.scenario == "error":
            return self.respond({"error": "Offline fixture: API unavailable"}, 503)
        if path == "/api/collection/overview":
            result = overview(self.server.runtime, challenge=self.server.challenge, restart=self.server.restart)
            for index, (stage, key) in enumerate((("links", "unique_items"), ("details", "captured"), ("analysis", "finalized"))):
                result["modules"][stage][key] += self.server.growth[index]
            return self.respond(result)
        if path == "/api/collection/regions":
            return self.respond({"regions": REGIONS})
        if path == "/api/collection/items":
            return self.respond(item_list(
                query.get("stage", ["links"])[0],
                max(1, min(50, int(query.get("limit", [10])[0]))),
                max(0, int(query.get("offset", [0])[0])),
                self.server.scenario == "empty",
            ))
        if path == "/api/collection/item":
            return self.respond(item_detail(query.get("item_id", [""])[0], self.server.updates))
        return self.respond({"error": "No production API is available"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if not 0 <= length <= 65536:
            return self.respond({"error": "Body too large"}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return self.respond({"error": "Invalid JSON"}, 400)
        if not isinstance(body, dict):
            return self.respond({"error": "Expected an object"}, 400)
        path = urlsplit(self.path).path
        if path == "/__preview/state":
            if body.get("reset_events") is True:
                self.server.events.clear()
            self.server.scenario = body.get("scenario", "normal")
            self.server.delay = max(0, min(3, float(body.get("delay", 0))))
            self.server.challenge = bool(body.get("challenge", self.server.challenge))
            self.server.restart = body.get("restart", self.server.restart)
            if isinstance(body.get("growth"), list) and len(body["growth"]) == 3:
                self.server.growth = [int(value) for value in body["growth"]]
            return self.respond({"ok": True})
        if path in {
            "/api/collection/control/pause", "/api/collection/control/start",
            "/api/collection/control/restart",
        } and self.headers.get("X-FAPAI-Control-Token") != "offline-fixture-operator-token-00001":
            return self.respond({"error": "Fixture authorization rejected"}, 403)
        self.server.events.append({"path": path, "body": body})
        if path == "/api/collection/item/manual_update":
            item_id = str(body["item_id"])
            self.server.updates[item_id] = body["updates"]
            return self.respond({
                "flat_item": item_detail(item_id, self.server.updates)["flat_item"],
                "updated_fields": list(body["updates"]),
            })
        if path == "/api/collection/item/reanalyze":
            return self.respond({"ok": True, "analysis_attempt_count": 3})
        if path == "/api/collection/region/reset_links":
            return self.respond({"ok": True})
        if path == "/api/collection/control/pause":
            self.server.runtime = "暂停中"
            return self.respond({"runtime_state": self.server.runtime})
        if path == "/api/collection/control/start":
            self.server.runtime = "运行中"
            return self.respond({"ok": True})
        if path == "/api/collection/control/restart":
            self.server.restart = {"available": True, "request": {"id": body["request_id"], "status": "requested"}}
            return self.respond({"ok": True, "created": True, "request": self.server.restart["request"]})
        if path == "/api/collection/auth/complete":
            self.server.runtime = "运行中"
            self.server.challenge = False
            return self.respond({"runtime_state": self.server.runtime})
        return self.respond({"error": "No production mutation is available"}, 404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=1436)
    args = parser.parse_args()
    if not (DIST / "index.html").is_file():
        parser.error("Build collector-desktop first.")
    server = PreviewServer(args.port)
    print(f"OFFLINE FIXTURES ONLY: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
