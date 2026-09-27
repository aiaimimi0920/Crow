"""Exact API routes. Prefix matching is reserved for static assets and item IDs."""

GET_GROUPS = {
    "_get_collection_index": ("/collection", "/collection/"),
    "_get_collection_overview": ("/api/collection/overview",),
    "_get_collection_items": ("/api/collection/items",),
    "_get_collection_regions": ("/api/collection/regions",),
    "_get_collection_item": ("/api/collection/item",),
    "_get_collection_job": ("/api/collection/jobs",),
    "_get_auth_recovery": ("/api/collection/auth/recovery",),
    "_get_auth_recovery_snapshot": ("/api/collection/auth/recovery/snapshot",),
    "_get_status": ("/api/status",),
    "_get_analysis_prediction": ("/api/avm/predict", "/api/analysis/predict"),
    "_get_analysis_health": (
        "/api/avm/health",
        "/api/analysis/health",
        "/api/analysis/status",
    ),
    "_get_collection_template": ("/api/avm/collection_template",),
    "_get_pipeline_status": ("/api/avm/pipeline_status",),
    "_get_merge_check": ("/api/avm/merge_check",),
    "_get_item": ("/api/get_item",),
}

POST_GROUPS = {
    "_post_collection_job_cancel": ("/api/collection/jobs/cancel",),
    "_post_drift_report": ("/api/avm/drift_status", "/api/analysis/drift_status"),
    "_post_release_gate": ("/api/avm/release_gate", "/api/analysis/release_gate"),
    "_post_recent_gap_audit": ("/api/avm/recent_gap_audit",),
    "_post_seed_next_task": (
        "/api/get_or_create_sniff_task",
        "/api/collection/seeds/next_task",
    ),
    "_post_detail_tasks": ("/api/get_tasks", "/api/collection/details/tasks"),
    "_post_detail_next_task": ("/api/next_task", "/api/collection/details/next_task"),
    "_post_recent_detail_replay": ("/api/avm/recent_detail_replay",),
    "_post_seed_progress": (
        "/api/report_sniff_status",
        "/api/collection/seeds/report_progress",
    ),
    "_post_region_reset_links": ("/api/collection/region/reset_links",),
    "_post_item_reanalyze": ("/api/collection/item/reanalyze",),
    "_post_item_manual_update": ("/api/collection/item/manual_update",),
    "_post_collection_start": ("/api/collection/control/start",),
    "_post_collection_control": (
        "/api/collection/control/pause",
        "/api/collection/control/resume",
    ),
    "_post_desktop_auth_request": ("/api/collection/auth/recovery/request",),
    "_post_auth_recovery_transition": (
        "/api/collection/auth/recovery/heartbeat",
        "/api/collection/auth/recovery/claim",
        "/api/collection/auth/recovery/snapshot_ready",
        "/api/collection/auth/recovery/pc2_restarting",
        "/api/collection/auth/recovery/result",
    ),
    "_post_auth_force_reset": ("/api/collection/auth/force_reset",),
    "_post_auth_complete": ("/api/collection/auth/complete",),
    "_post_auth_resume_after_cooldown": ("/api/collection/auth/resume_after_cooldown",),
    "_post_analysis_run": ("/api/avm/run", "/api/analysis/pipeline/run"),
    "_post_analysis_evaluate": ("/api/avm/evaluate", "/api/analysis/evaluate"),
    "_post_detail_maintenance": (
        "/api/avm/recent_enrich_maintenance",
        "/api/collection/details/maintenance",
    ),
    "_post_fetch_missing_detail_archives": (
        "/api/avm/fetch_missing_detail_archives",
        "/api/collection/details/fetch_missing",
    ),
    "_post_archive_detail_replay": (
        "/api/avm/archive_detail_replay",
        "/api/collection/details/prepare_replay",
    ),
    "_post_start_all_subtasks": ("/api/avm/start_all_subtasks",),
    "_post_run_all_subtasks_sync": ("/api/avm/run_all_subtasks_sync",),
    "_post_save_locations": ("/api/save_locations",),
    "_post_area_result": ("/api/area_result", "/api/collection/details/area_result"),
    "_post_infer_location": (
        "/api/infer_location",
        "/api/collection/details/infer_location",
    ),
    "_post_approve_area": ("/api/approve_area", "/api/collection/details/approve_area"),
    "_post_seed_batch": ("/api/save", "/api/collection/seeds/batch"),
    "_post_analysis_screen": ("/api/avm/screen",),
    "_post_captcha_report": ("/api/report_captcha", "/api/report_manual_captcha"),
    "_post_client_log": ("/api/log",),
    "_post_upload": ("/api/upload",),
    "_post_detail_update_item": (
        "/api/update_item",
        "/api/collection/details/update_item",
    ),
    "_post_detail_next_visit": ("/api/get_next_task",),
    "_post_detail_html": ("/api/analyze_html", "/api/collection/details/html"),
}

RETIRED_GET_ROUTES = {
    path: path
    for handler in (
        "_post_seed_next_task",
        "_post_detail_tasks",
        "_post_detail_next_task",
        "_post_recent_detail_replay",
        "_post_fetch_missing_detail_archives",
        "_post_archive_detail_replay",
        "_post_drift_report",
        "_post_release_gate",
        "_post_recent_gap_audit",
    )
    for path in POST_GROUPS[handler]
}
RETIRED_GET_ROUTES["/api/resume"] = "/api/collection/control/resume"


def build_routes(
    get_groups: dict[str, tuple[str, ...]], post_groups: dict[str, tuple[str, ...]]
) -> dict[tuple[str, str], str]:
    routes = {}
    for method, groups in (("GET", get_groups), ("POST", post_groups)):
        for handler, paths in groups.items():
            for path in paths:
                key = (method, path)
                if key in routes:
                    raise ValueError(f"Duplicate route: {method} {path}")
                routes[key] = handler
    return routes
