"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def main(argv: Sequence[str] | None = None) -> int:
    from tools.detail_worker_sessions import OwnedRuntimeContext
    from tools.worker_lifecycle import WorkerLifecycle

    config, loop = config_from_env_and_args(argv)
    # Allow running without LLM for raw data collection
    # if not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY"):
    #     raise RuntimeError("OPENAI_BASE_URL/OPENAI_API_KEY must be set for detail-worker mode")
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for detail-worker mode")

    with (
        WorkerLifecycle(config.worker_id, repository.release_seed_detail_worker_leases),
        OwnedRuntimeContext(
            lambda: (
                (None, {}) if config.analysis_only else _build_runtime_context(config)
            )
        ) as context,
    ):
        if loop:
            summary = run_detail_worker_loop(
                config,
                repository=repository,
                runtime_context_factory=context,
            )
        else:
            http_session, browser_pages = context()
            summary = run_detail_worker_batch(
                config,
                repository=repository,
                http_session=http_session,
                browser_pages=browser_pages,
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


__all__ = ("main",)
