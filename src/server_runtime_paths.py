"""Bootstrap path defaults without constructing the server runtime."""

from pathlib import Path

from src.project_environment import getenv as project_getenv

# Runtime initialization still replaces the legacy relative data directory.
DATA_DIR = "datas"
NAS_AUTH_RECOVERY_STATE_PATH = Path(
    project_getenv("CROW_NAS_AUTH_RECOVERY_STATE_PATH")
    or Path(project_getenv("CROW_SOLVER_STATE_DIR") or DATA_DIR)
    / "nas-auth-recovery.json"
)
NAS_AUTH_RECOVERY_TOKEN_FILE = Path(
    project_getenv("CROW_NAS_AUTH_RECOVERY_TOKEN_FILE")
    or Path(project_getenv("CROW_SOLVER_STATE_DIR") or DATA_DIR)
    / "nas-auth-recovery.token"
)
