"""PC2 solver environment defaults without browser or recovery initialization."""

from pathlib import Path

from src.project_environment import getenv as project_getenv

REPO_ROOT = Path(__file__).resolve().parents[1]

# Remote topology is supplied by the installation, with loopback for development.
DEFAULT_API_BASE_URL = project_getenv("CROW_API_BASE_URL", "http://127.0.0.1:8001/api")
DEFAULT_CDP_ENDPOINT = project_getenv("CROW_CDP_ENDPOINT", "http://127.0.0.1:9223")
DEFAULT_POLL_SECONDS = int(project_getenv("CROW_LOCAL_SOLVER_POLL_SECONDS", "5"))
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_DRAG_PROFILE_VARIANTS = 3

AUTH_COMPLETE_REQUEST_ATTEMPTS = int(
    project_getenv("CROW_AUTH_COMPLETE_REQUEST_ATTEMPTS", "3")
)
AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS = float(
    project_getenv("CROW_AUTH_COMPLETE_REQUEST_TIMEOUT_SECONDS", "15")
)
AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS = float(
    project_getenv("CROW_AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", "1")
)
AUTH_COMPLETE_RETRY_BASE_SECONDS = float(
    project_getenv("CROW_AUTH_COMPLETE_RETRY_BASE_SECONDS", "5")
)
AUTH_COMPLETE_RETRY_MAX_SECONDS = float(
    project_getenv("CROW_AUTH_COMPLETE_RETRY_MAX_SECONDS", "60")
)
AUTH_COMPLETE_PENDING_MAX_SECONDS = float(
    project_getenv("CROW_AUTH_COMPLETE_PENDING_MAX_SECONDS", "120")
)
RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS = float(
    project_getenv("CROW_RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS", "3600")
)
POST_AUTH_CDP_PROBE_GRACE_SECONDS = float(
    project_getenv("CROW_POST_AUTH_CDP_PROBE_GRACE_SECONDS", "180")
)
SOLVER_EXECUTION_TIMEOUT_SECONDS = float(
    project_getenv("CROW_LOCAL_SOLVER_EXECUTION_TIMEOUT_SECONDS", "180")
)
SOLVER_TERMINATE_GRACE_SECONDS = float(
    project_getenv("CROW_LOCAL_SOLVER_TERMINATE_GRACE_SECONDS", "5")
)
SOLVER_HEARTBEAT_PATH = Path(
    project_getenv(
        "CROW_LOCAL_SOLVER_HEARTBEAT_PATH",
        "/tmp/fapaifang-local-solver-heartbeat.json",
    )
)
AUTH_RECOVERY_SNAPSHOT_PATH = Path(
    project_getenv("CROW_NAS_AUTH_RECOVERY_SNAPSHOT_PATH")
    or project_getenv(
        "CROW_COOKIE_SNAPSHOT", "/data/secrets/nodes/pc2/taobao-cookies.json"
    )
)
AUTH_RECOVERY_MARKER_PATH = Path(
    project_getenv(
        "CROW_NAS_AUTH_RECOVERY_MARKER_PATH",
        str(REPO_ROOT / ".codex-temp" / "bridge-control" / "pc2-auth-recovery.json"),
    )
)
AUTH_RECOVERY_TOKEN_PATH = Path(
    project_getenv(
        "CROW_NAS_AUTH_RECOVERY_TOKEN_FILE", "/data/secrets/nas-auth-recovery.token"
    )
)
