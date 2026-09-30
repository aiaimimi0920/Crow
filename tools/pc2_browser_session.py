"""Preserve the existing session across a bounded collection-browser restart."""

import json
import subprocess
import time
import uuid

from .pc2_settings_runtime import run

EXPORT = """
import hashlib,json,os,pathlib,websocket
from tools.pc2_auth_recovery import _cdp_call,fetch_json
path=pathlib.Path({path!r})
version=fetch_json(os.environ['FAPAI_CDP_ENDPOINT'].rstrip('/')+'/json/version',timeout=5)
connection=websocket.create_connection(version['webSocketDebuggerUrl'],timeout=10,suppress_origin=True)
try: cookies=_cdp_call(connection,1,'Storage.getCookies',dict())['cookies']
finally: connection.close()
cookies=[c for c in cookies if c['domain']=='taobao.com' or c['domain'].endswith('.taobao.com')]
if not cookies:raise ValueError('No session to preserve')
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(cookies,stream)
print(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
"""
RESTORE = """
import json,os
from tools.pc2_auth_recovery import import_cookie_snapshot_to_cdp
result=import_cookie_snapshot_to_cdp({path!r},os.environ['FAPAI_CDP_ENDPOINT'],expected_sha256={sha256!r})
print(json.dumps(dict(verified=result['verified_session_cookie_count']==result['session_cookie_count'])))
"""


class BrowserSession:
    def __init__(self, *, runner=run, sleep=time.sleep):
        self.run, self.sleep = runner, sleep

    def capture(self, row):
        directory = "/app/.codex-temp/bridge-control"
        # Refuse a restart if its private session backup would be ephemeral.
        if not any(
            m.get("RW")
            and (
                directory == m.get("Destination")
                or directory.startswith(str(m.get("Destination", "")).rstrip("/") + "/")
            )
            for m in row.get("Mounts", [])
            if m.get("Destination")
        ):
            raise ValueError("Persistent session mount unavailable")
        path = directory + "/progress-restart-" + uuid.uuid4().hex + ".json"
        output = self.run(
            ["exec", row["Id"], "python", "-c", EXPORT.format(path=path)], timeout=30
        )
        receipt = json.loads(output)
        if (
            receipt.get("path") != path
            or not isinstance(receipt.get("sha256"), str)
            or len(receipt["sha256"]) != 64
        ):
            raise ValueError("Invalid session checkpoint receipt")
        return receipt

    def restore(self, container_id, receipt):
        code = RESTORE.format(**receipt)
        for _ in range(30):
            try:
                result = json.loads(
                    self.run(["exec", container_id, "python", "-c", code], timeout=20)
                )
                if result.get("verified") is True:
                    return
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                pass
            self.sleep(2)
        raise RuntimeError("Session restore not verified; checkpoint retained")
