"""Bootstrap path defaults without constructing the server runtime."""

import os
from pathlib import Path

# Runtime initialization still replaces the legacy relative data directory.
DATA_DIR = "datas"
NAS_AUTH_RECOVERY_STATE_PATH = Path(
    os.getenv("FAPAI_NAS_AUTH_RECOVERY_STATE_PATH")
    or Path(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR) / "nas-auth-recovery.json"
)
NAS_AUTH_RECOVERY_TOKEN_FILE = Path(
    os.getenv("FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE")
    or Path(os.getenv("FAPAI_SOLVER_STATE_DIR") or DATA_DIR) / "nas-auth-recovery.token"
)
