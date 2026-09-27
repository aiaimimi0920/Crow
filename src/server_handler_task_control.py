from __future__ import annotations

import logging
import sys
import time  # noqa: F401 - direct-module recovery clock
from typing import cast

from .auth_command_handlers import AuthCommandHost, bind_auth_commands
from .auth_recovery_transition_handler import (
    RecoveryTransitionHost,
    bind_recovery_transitions,
)
from .detail_dispatch_handlers import DetailDispatchHost, bind_detail_dispatch
from .observer_command_handlers import ObserverCommandHost, bind_observer_commands
from .seed_task_handlers import SeedTaskHost, bind_seed_tasks
from .server_context import (
    AVM_PIPELINE,  # noqa: F401 - direct-module pipeline host
    DB_REPOSITORY,  # noqa: F401 - direct-module item host
    DISPATCH_COOLDOWN_SECONDS,  # noqa: F401 - direct-module dispatch host
    NAS_AUTH_RECOVERY,  # noqa: F401 - direct-module recovery host
)
from .task_read_handlers import TaskReadHost, bind_task_reads

logger = logging.getLogger(__name__)

_task_reads = bind_task_reads(cast(TaskReadHost, sys.modules[__name__]))
_post_recent_detail_replay = _task_reads._post_recent_detail_replay
_get_pipeline_status = _task_reads._get_pipeline_status
_get_merge_check = _task_reads._get_merge_check
_get_item = _task_reads._get_item
_get_api_not_found = _task_reads._get_api_not_found
_server_get_fallback = _task_reads._server_get_fallback

_seed_tasks = bind_seed_tasks(cast(SeedTaskHost, sys.modules[__name__]))
_post_seed_next_task = _seed_tasks._post_seed_next_task
_post_seed_progress = _seed_tasks._post_seed_progress

_post_detail_tasks = bind_detail_dispatch(
    cast(DetailDispatchHost, sys.modules[__name__])
)._post_detail_tasks

_observer_commands = bind_observer_commands(
    cast(ObserverCommandHost, sys.modules[__name__])
)
_post_region_reset_links = _observer_commands._post_region_reset_links
_post_item_reanalyze = _observer_commands._post_item_reanalyze
_post_item_manual_update = _observer_commands._post_item_manual_update
_post_collection_control = _observer_commands._post_collection_control

_post_auth_recovery_transition = bind_recovery_transitions(
    cast(RecoveryTransitionHost, sys.modules[__name__])
)._post_auth_recovery_transition

_auth_commands = bind_auth_commands(cast(AuthCommandHost, sys.modules[__name__]))
_post_auth_force_reset = _auth_commands._post_auth_force_reset
_post_auth_complete = _auth_commands._post_auth_complete
_post_auth_resume_after_cooldown = _auth_commands._post_auth_resume_after_cooldown

__all__ = [  # noqa: RUF022 - preserve legacy export ordering
    "_post_recent_detail_replay",
    "_get_pipeline_status",
    "_get_merge_check",
    "_get_item",
    "_post_seed_next_task",
    "_post_detail_tasks",
    "_get_api_not_found",
    "_server_get_fallback",
    "_post_seed_progress",
    "_post_region_reset_links",
    "_post_item_reanalyze",
    "_post_item_manual_update",
    "_post_collection_control",
    "_post_auth_recovery_transition",
    "_post_auth_force_reset",
    "_post_auth_complete",
    "_post_auth_resume_after_cooldown",
]
