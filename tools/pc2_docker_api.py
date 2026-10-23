"""Small local Docker transport; credentials and clone payloads never enter argv."""

import http.client
import json
import re
import socket
from copy import deepcopy
from urllib.parse import urlencode


class DockerAPIError(RuntimeError):
    pass


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


class DockerAPI:
    def __init__(self):
        version = self.request("GET", "/version", versioned=False).get("ApiVersion", "")
        if not re.fullmatch(r"1\.\d+", version):
            raise DockerAPIError("Invalid local Docker API version")
        self.version = "/v" + version

    def request(self, method, path, body=None, *, versioned=True):
        connection = UnixConnection("localhost", timeout=120)
        try:
            data = None if body is None else json.dumps(body).encode("utf-8")
            connection.request(
                method,
                (self.version if versioned else "") + path,
                body=data,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            if response.status >= 400 or len(raw) > 4 * 1024 * 1024:
                # Docker errors can contain environment and host paths; keep them private.
                raise DockerAPIError(
                    "Local Docker operation failed: HTTP " + str(response.status)
                )
            return json.loads(raw) if raw else None
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise DockerAPIError("Local Docker transport failed") from exc
        finally:
            connection.close()

    def inspect(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise DockerAPIError("An exact container ID is required")
        return self.request("GET", "/containers/" + identifier + "/json")

    def action(self, identifier, action, body=None, **query):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise DockerAPIError("An exact container ID is required")
        return self.request(
            "POST",
            "/containers/"
            + identifier
            + "/"
            + action
            + ("?" + urlencode(query) if query else ""),
            body,
        )

    def create(self, name, payload):
        return self.request(
            "POST", "/containers/create?" + urlencode({"name": name}), payload
        )["Id"]


def clone_payload(row, environment):
    """Retain inspected runtime settings, but not allocated network identities."""
    result = deepcopy(row["Config"])
    result.update(
        Image=row["Image"],
        Env=[key + "=" + str(value) for key, value in environment.items()],
    )
    host = deepcopy(row["HostConfig"])
    if host.get("AutoRemove"):
        raise ValueError("Automatic removal is incompatible with retained rollback")
    host["RestartPolicy"] = {"Name": "no", "MaximumRetryCount": 0}
    result["HostConfig"] = host
    if host.get("NetworkMode") not in {"host", "none"} and not host.get(
        "NetworkMode", ""
    ).startswith("container:"):
        endpoints = {}
        for name, endpoint in row["NetworkSettings"]["Networks"].items():
            endpoints[name] = {
                key: deepcopy(endpoint[key])
                for key in ("IPAMConfig", "Links", "DriverOpts")
                if endpoint.get(key)
            }
            aliases = [
                alias
                for alias in endpoint.get("Aliases") or []
                if alias not in {row["Id"], row["Id"][:12], row["Name"].lstrip("/")}
            ]
            if aliases:
                endpoints[name]["Aliases"] = aliases
        result["NetworkingConfig"] = {"EndpointsConfig": endpoints}
    return result
