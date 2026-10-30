"""In-memory Docker state for cooperative maintenance tests; no live I/O."""

from copy import deepcopy


class FakeDetailDocker:
    def __init__(self, *, finish_after=2, exit_code=0):
        self.now, self.finish_after, self.exit_code = 0, finish_after, exit_code
        self.calls, self.pending, self.failures = [], {}, {}
        self.rows = {}
        for n in range(1, 4):
            name = f"fapaifang-pc2-detail-{n}"
            self.rows[name] = {
                "Id": f"{n:064x}",
                "Name": "/" + name,
                "Image": "sha256:" + "a" * 64,
                "Config": {"Env": ["PRIVATE_TEST_VALUE=not-for-safe-receipts"]},
                "HostConfig": {
                    "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
                    "Other": "preserved",
                },
                "Mounts": [
                    {"Source": "/fixture/data", "Destination": "/data", "RW": True}
                ],
                "State": {
                    "Running": True,
                    "Pid": 100 + n,
                    "StartedAt": "original",
                    "ExitCode": 0,
                    "Health": {"Status": "healthy"},
                },
            }
        self.original = deepcopy(self.rows)
        self.expected = {
            name: {"id": row["Id"], "image": row["Image"], "pid": row["State"]["Pid"]}
            for name, row in self.rows.items()
        }

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def inspect(self, name):
        row = self.rows[name]
        if name in self.pending and self.now >= self.pending[name]:
            row["State"].update(Running=False, Pid=0, ExitCode=self.exit_code)
            del self.pending[name]
        return deepcopy(row)

    def action(self, identity, action, body=None):
        name = next(name for name, row in self.rows.items() if row["Id"] == identity)
        self.calls.append((name, action, deepcopy(body)))
        if self.failures.pop((name, action), False):
            raise RuntimeError("fixture operation failure")
        row = self.rows[name]
        if action == "update":
            row["HostConfig"]["RestartPolicy"] = deepcopy(body["RestartPolicy"])
        elif action == "kill?signal=SIGTERM":
            assert all(
                value["HostConfig"]["RestartPolicy"]["Name"] == "no"
                for value in self.rows.values()
            )
            self.pending[name] = self.now + self.finish_after
        elif action == "start":
            assert not row["State"]["Running"]
            row["State"].update(
                Running=True,
                Pid=self.original[name]["State"]["Pid"] + 1000,
                StartedAt="restored",
                ExitCode=0,
            )
        else:
            raise AssertionError(
                "No force-stop or broad lifecycle operation is allowed"
            )
