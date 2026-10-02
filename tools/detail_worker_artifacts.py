"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def _build_runtime_context(config: DetailWorkerConfig) -> RuntimeContext:
    cookies = export_cookies(config.cdp_endpoint)
    browser_pages = (
        {}
        if not _env_bool("FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES", False)
        else load_open_browser_pages(config.cdp_endpoint)
    )
    return build_http(cookies), browser_pages


def _emit_progress_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _detail_batch_progress_event(run: int, result: dict[str, Any]) -> dict[str, Any]:
    results = result.get("results") if isinstance(result.get("results"), list) else []
    last_result = results[-1] if results and isinstance(results[-1], dict) else {}
    return {
        "event": "detail_worker_batch",
        "run": run,
        "decision": result.get("decision"),
        "attempts": result.get("attempts"),
        "completed": result.get("completed"),
        "target_success": result.get("target_success"),
        "max_attempts": result.get("max_attempts"),
        "last_result_decision": last_result.get("decision"),
        "last_item_id": last_result.get("item_id"),
        "counts": result.get("counts"),
    }


def _load_final_item(output_dir: Path, item_id: str) -> dict[str, Any] | None:
    path = output_dir / item_id / "final.json"
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _record_analysis_module_b_receipt(
    repository: PropertyRepository,
    *,
    item_id: str,
    receipt: Any,
) -> None:
    if not isinstance(receipt, dict) or not receipt.get("run_id"):
        return
    record_run = getattr(repository, "record_analysis_ensemble_run", None)
    if not callable(record_run):
        return
    try:
        record_run(item_id, receipt)
    except Exception as persistence_error:
        print(
            "[ANALYSIS-MODULE-B] unable to persist run receipt "
            f"for {item_id}: {safe_exception_text(persistence_error)}"
        )


def _load_analysis_module_b_latest(output_dir: Path, item_id: str) -> dict[str, Any] | None:
    path = output_dir / item_id / "analysis-b" / "latest.json"
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _copy_raw_artifact(source_value: Any, target_path: Path) -> str | None:
    source_text = str(source_value or "").strip()
    if not source_text:
        return None
    source_path = Path(source_text)
    if not source_path.exists():
        return None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_path.resolve() == target_path.resolve():
            return str(target_path)
    except OSError:
        pass
    shutil.copyfile(source_path, target_path)
    return str(target_path)


def _write_durable_detail_archive(
    *,
    archive_root: Path,
    detail_html_path: Path,
    item_id: str,
    captured_at: datetime.datetime | None = None,
) -> str:
    """把 raw detail HTML 复制到日期分区的持久归档，返回归档路径。

    `output_dir/{item_id}/detail.html` 是分析阶段用的临时工作副本，会被后续任务
    覆盖或清掉；线上 228,959 行的 detail_archive_path 全空、磁盘不留 HTML 就是
    因为生产路径从来没有落过持久副本。抽取逻辑将来改进时，回填需要这份原料。

    路径是确定性的：`{archive_root}/html_archive/{YYYY}/{YYYY-MM-DD}/item-{id}.html`，
    回填工具可以按 item_id 直接 glob，不依赖 DB 里记的路径。
    """
    moment = captured_at or datetime.datetime.now()
    target_dir = archive_root / "html_archive" / moment.strftime("%Y") / moment.strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"item-{item_id}.html"
    shutil.copyfile(detail_html_path, target_path)
    return str(target_path)


def _archive_raw_detail_if_configured(
    *,
    config: DetailWorkerConfig,
    detail_html_path: Path,
    item_id: str,
) -> str:
    """按配置归档，且不让归档失败影响已经成功的抓取。

    抓取成本远高于归档：抓取成功后因为磁盘满或权限问题把整条判失败，会让 item
    重新排队再抓一次，这比丢一份归档更糟。所以这里吞掉异常只记日志。
    """
    archive_root = config.detail_archive_root
    if archive_root is None:
        return ""
    if not detail_html_path.is_file():
        return ""
    try:
        return _write_durable_detail_archive(
            archive_root=Path(archive_root),
            detail_html_path=detail_html_path,
            item_id=item_id,
        )
    except Exception as archive_error:
        print(f"[DETAIL-ARCHIVE] durable archive failed for {item_id}: {safe_exception_text(archive_error)}")
        return ""


def _stage_raw_detail_artifacts_for_analysis(seed: dict[str, Any], *, output_dir: Path, item_id: str) -> dict[str, Any]:
    item_dir = output_dir / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    seed_payload = dict(seed)
    write_json(item_dir / "seed.json", seed_payload)

    artifacts = seed.get("_raw_detail_artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    staged = {
        "detail_html_path": _copy_raw_artifact(artifacts.get("detail_html_path"), item_dir / "detail.html"),
        "description_json_path": _copy_raw_artifact(artifacts.get("description_json_path"), item_dir / "description-data.json"),
        "selected_json_path": _copy_raw_artifact(artifacts.get("selected_json_path"), item_dir / "selected.json"),
    }
    return {key: value for key, value in staged.items() if value}


def _raw_detail_final_url(selected_json_path: Path) -> str:
    if not selected_json_path.exists():
        return ""
    try:
        selected = load_json(selected_json_path)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(selected, dict):
        return ""
    fetch = selected.get("fetch")
    if not isinstance(fetch, dict):
        return ""
    return str(fetch.get("detail_final_url") or "")


def _assert_raw_detail_artifact_is_not_challenge(*, detail_html_path: Path, selected_json_path: Path) -> None:
    try:
        html = detail_html_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"raw detail artifact missing or unreadable: {detail_html_path}") from exc
    final_url = _raw_detail_final_url(selected_json_path)
    if is_challenge_page(html, final_url):
        raise RuntimeError(f"raw detail artifact returned anti-bot challenge: {final_url}")


__all__ = (
    '_build_runtime_context',
    '_emit_progress_event',
    '_detail_batch_progress_event',
    '_load_final_item',
    '_record_analysis_module_b_receipt',
    '_load_analysis_module_b_latest',
    '_copy_raw_artifact',
    '_write_durable_detail_archive',
    '_archive_raw_detail_if_configured',
    '_stage_raw_detail_artifacts_for_analysis',
    '_raw_detail_final_url',
    '_assert_raw_detail_artifact_is_not_challenge',
)
