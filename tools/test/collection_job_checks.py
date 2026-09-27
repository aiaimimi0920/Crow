"""Bounded polling for tests of the public asynchronous operation contract."""

import json
import time
from urllib.request import Request, urlopen


def wait_for_job(fetch, status_url, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        job = fetch(status_url)
        if job["status"] not in {"queued", "running", "cancelling"}:
            return job
        if time.monotonic() >= deadline:
            raise AssertionError(f"Collection job did not finish: {job['job_id']}")
        time.sleep(0.01)


def wait_for_http_job(base_url, status_url, headers, timeout=5):
    def fetch(path):
        request = Request(base_url + path, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    return wait_for_job(fetch, status_url, timeout=timeout)
