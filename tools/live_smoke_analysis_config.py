from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403
from tools.live_smoke_auth import *  # noqa: F401,F403
from tools.live_smoke_cdp import *  # noqa: F401,F403
from tools.live_smoke_browser import *  # noqa: F401,F403
from tools.live_smoke_summary import *  # noqa: F401,F403


ANALYSIS_MODULE_B_DEFAULT_MODELS = (
    "DeepSeek-V4-Flash",
    "DeepSeek-V4-Pro-0813",
    "gemini-3.1-flash",
)

ANALYSIS_MODULE_B_DEFAULT_ARBITER = "grok-4.6"

ANALYSIS_PROVENANCE_FIELD = "analysis_provenance"

class AnalysisModuleBIncompleteError(RuntimeError):
    pass

def _analysis_module_b_mode() -> str:
    mode = str(project_getenv("CROW_ANALYSIS_MODULE_B_MODE") or "off").strip().lower()
    if mode not in {"off", "shadow", "primary"}:
        raise ValueError("CROW_ANALYSIS_MODULE_B_MODE must be one of: off, shadow, primary")
    return mode

def _analysis_module_b_models() -> tuple[str, ...]:
    from src.analysis_ensemble import parse_distinct_models
    from src.llm_helper import require_non_gpt_analysis_model

    configured = str(project_getenv("CROW_ANALYSIS_MODULE_B_CANDIDATE_MODELS") or "").strip()
    return tuple(
        require_non_gpt_analysis_model(model, setting="CROW_ANALYSIS_MODULE_B_CANDIDATE_MODELS")
        for model in parse_distinct_models(configured or ANALYSIS_MODULE_B_DEFAULT_MODELS)
    )

def _analysis_module_b_arbiter_model() -> str:
    from src.llm_helper import require_non_gpt_analysis_model

    model = str(
        project_getenv("CROW_ANALYSIS_MODULE_B_ARBITER_MODEL")
        or ANALYSIS_MODULE_B_DEFAULT_ARBITER
    ).strip()
    return require_non_gpt_analysis_model(model, setting="CROW_ANALYSIS_MODULE_B_ARBITER_MODEL")

def _analysis_module_b_parallelism() -> int:
    raw = project_getenv("CROW_ANALYSIS_MODULE_B_MAX_PARALLEL")
    try:
        configured = int(raw or "3")
    except ValueError:
        configured = 3
    return min(max(configured, 1), 3)

def _analysis_module_b_candidate_attempts() -> int:
    raw = project_getenv("CROW_ANALYSIS_MODULE_B_CANDIDATE_ATTEMPTS")
    try:
        configured = int(raw or "3")
    except ValueError:
        configured = 3
    return min(max(configured, 1), 5)

def _analysis_module_b_candidate_retry_seconds() -> float:
    raw = project_getenv("CROW_ANALYSIS_MODULE_B_CANDIDATE_RETRY_SECONDS")
    try:
        configured = float(raw or "10")
    except ValueError:
        configured = 10.0
    return min(max(configured, 0.0), 60.0)

def _analysis_module_b_retryable_candidate_error(exc: BaseException) -> bool:
    if isinstance(exc, (json.JSONDecodeError, requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return status_code in {408, 409, 425, 429, 500, 502, 503, 504, 524}
    # Model output can be syntactically valid JSON but still fail shape validation.
    return isinstance(exc, ValueError)

def _analysis_module_b_shadow_sample_rate() -> float:
    configured = str(
        project_getenv("CROW_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE") or "0.01"
    ).strip()
    try:
        rate = float(configured)
    except ValueError as exc:
        raise ValueError(
            "CROW_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE must be a number from 0 to 1"
        ) from exc
    if not 0 <= rate <= 1:
        raise ValueError(
            "CROW_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE must be a number from 0 to 1"
        )
    return rate

def _analysis_module_b_shadow_selected(item_id: str) -> bool:
    rate = _analysis_module_b_shadow_sample_rate()
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    bucket = int.from_bytes(hashlib.sha256(str(item_id).encode("utf-8")).digest()[:8], "big")
    return bucket / 2**64 < rate

def _safe_module_b_error(exc: BaseException) -> dict[str, str]:
    return safe_exception_details(exc)

def _module_b_cached_candidate(
    path: Path,
    *,
    model: str,
    input_sha256: str,
    raw_html_sha256: str,
) -> dict[str, Any] | None:
    from src.analysis_ensemble import ANALYSIS_MODULE_B_VERSION

    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("schema_version") != ANALYSIS_MODULE_B_VERSION
        or payload.get("model") != model
        or payload.get("input_sha256") != input_sha256
        or payload.get("raw_html_sha256") != raw_html_sha256
    ):
        return None
    return payload if isinstance(payload.get("result"), dict) else None

def _run_analysis_module_b(
    *,
    item_id: str,
    item_dir: Path,
    analysis_text: str,
    evidence_text: str,
    html: str,
    effective_seed: dict[str, Any],
    do_risk: bool,
    mode: str,
    adapter: CollectionAdapter | None = None,
) -> dict[str, Any]:
    from src import llm_helper
    from src.analysis_ensemble import (
        ANALYSIS_MODULE_B_VERSION,
        build_adjudication_prompt,
        build_field_consensus,
        compose_final_payload,
        final_status,
        validate_adjudication,
    )
    from src.collection.runtime_adapter import extract_detail_payload, resolve_record_adapter

    active_adapter = resolve_record_adapter(effective_seed, configured=adapter)

    models = _analysis_module_b_models()
    arbiter_model = _analysis_module_b_arbiter_model()
    if mode == "primary" and arbiter_model in models:
        raise ValueError(
            "analysis module B primary mode requires an arbiter model independent from all three candidates"
        )
    candidate_input_sha256 = hashlib.sha256(analysis_text.encode("utf-8")).hexdigest()
    evidence_sha256 = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
    raw_html_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
    model_routing_sha256 = hashlib.sha256(
        json.dumps(
            {"candidate_models": list(models), "arbiter_model": arbiter_model},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    input_sha256 = hashlib.sha256(
        (
            f"candidate={candidate_input_sha256}\n"
            f"evidence={evidence_sha256}\n"
            f"raw_html={raw_html_sha256}\n"
            f"model_routing={model_routing_sha256}"
        ).encode("utf-8")
    ).hexdigest()
    run_id = hashlib.sha256(
        f"{item_id}|{ANALYSIS_MODULE_B_VERSION}|{input_sha256}".encode("utf-8")
    ).hexdigest()
    analysis_provenance = {
        "module": "B",
        "pipeline_version": ANALYSIS_MODULE_B_VERSION,
        "run_id": run_id,
        "input_sha256": input_sha256,
        "model_routing_sha256": model_routing_sha256,
    }
    run_dir = item_dir / "analysis-b" / ANALYSIS_MODULE_B_VERSION / input_sha256[:16]
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = run_dir / "receipt.json"
    latest_path = item_dir / "analysis-b" / "latest.json"
    candidate_paths = [run_dir / f"candidate-{index}.json" for index in range(1, 4)]

    candidate_records: list[dict[str, Any] | None] = [None, None, None]
    candidate_errors: list[dict[str, Any]] = []
    for index, (model, path) in enumerate(zip(models, candidate_paths)):
        candidate_records[index] = _module_b_cached_candidate(
            path,
            model=model,
            input_sha256=input_sha256,
            raw_html_sha256=raw_html_sha256,
        )

    def _analyze_candidate(index: int, model: str) -> tuple[int, dict[str, Any]]:
        max_attempts = _analysis_module_b_candidate_attempts()
        base_retry_seconds = _analysis_module_b_candidate_retry_seconds()
        for attempt in range(1, max_attempts + 1):
            try:
                extracted = json.loads(
                    extract_detail_payload(
                        analysis_text,
                        item_id=item_id,
                        adapter=active_adapter,
                        model=model,
                    )
                )
                if not isinstance(extracted, dict):
                    raise ValueError(f"candidate model {model} returned a non-object product payload")
                active_adapter.prepare_detail_record(extracted, existing=effective_seed, item_id=item_id)
                if do_risk and active_adapter.collects_avm_risk:
                    risk = llm_helper.extract_avm_risk_features(html, item_id=item_id, model=model)
                    if isinstance(risk, dict):
                        extracted["avm_risk_features"] = risk
                return index, {
                    "schema_version": ANALYSIS_MODULE_B_VERSION,
                    "candidate_index": index + 1,
                    "model": model,
                    "attempt_count": attempt,
                    "input_sha256": input_sha256,
                    "raw_html_sha256": raw_html_sha256,
                    "completed_at": utc_now_iso(),
                    "result": extracted,
                }
            except Exception as exc:
                if attempt >= max_attempts or not _analysis_module_b_retryable_candidate_error(exc):
                    raise
                wait_seconds = base_retry_seconds * (2 ** (attempt - 1))
                print(
                    json.dumps(
                        {
                            "event": "analysis_module_b_candidate_retry",
                            "item_id": item_id,
                            "candidate_index": index + 1,
                            "model": model,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "wait_seconds": wait_seconds,
                            "error_type": safe_exception_details(exc)["type"],
                        },
                        ensure_ascii=True,
                    )
                )
                if wait_seconds:
                    time.sleep(wait_seconds)
        raise AssertionError("analysis module B candidate retry loop exited unexpectedly")

    pending = [index for index, record in enumerate(candidate_records) if record is None]
    if pending:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(_analysis_module_b_parallelism(), len(pending)),
            thread_name_prefix="analysis-module-b",
        ) as executor:
            future_map = {
                executor.submit(_analyze_candidate, index, models[index]): index
                for index in pending
            }
            for future in concurrent.futures.as_completed(future_map):
                index = future_map[future]
                try:
                    completed_index, record = future.result()
                except Exception as exc:
                    candidate_errors.append(
                        {
                            "candidate_index": index + 1,
                            "model": models[index],
                            "error": _safe_module_b_error(exc),
                        }
                    )
                    continue
                candidate_records[completed_index] = record
                write_json(candidate_paths[completed_index], record)

    artifacts = {
        "run_dir": str(run_dir),
        "candidate_paths": [str(path) for path in candidate_paths],
        "consensus_path": str(run_dir / "consensus.json"),
        "conflicts_path": str(run_dir / "conflicts.json"),
        "adjudication_path": str(run_dir / "adjudication.json"),
        "final_path": str(run_dir / "final.json"),
        "receipt_path": str(receipt_path),
    }
    base_receipt = {
        "schema_version": ANALYSIS_MODULE_B_VERSION,
        "run_id": run_id,
        "item_id": item_id,
        "mode": mode,
        "input_sha256": input_sha256,
        "candidate_input_sha256": candidate_input_sha256,
        "evidence_sha256": evidence_sha256,
        "raw_html_sha256": raw_html_sha256,
        "model_routing_sha256": model_routing_sha256,
        "candidate_models": list(models),
        "arbiter_model": arbiter_model,
        "arbiter_independent_model": arbiter_model not in models,
        ANALYSIS_PROVENANCE_FIELD: analysis_provenance,
        "artifacts": artifacts,
        "updated_at": utc_now_iso(),
    }
    if any(record is None for record in candidate_records):
        receipt = {
            **base_receipt,
            "status": "candidate_partial",
            "candidate_success_count": sum(record is not None for record in candidate_records),
            "candidate_errors": candidate_errors,
        }
        write_json(receipt_path, receipt)
        write_json(latest_path, receipt)
        return receipt

    candidates = [record["result"] for record in candidate_records if record is not None]
    consensus = build_field_consensus(
        candidates,
        source_text=evidence_text,
        profile=active_adapter.analysis_profile,
    )
    consensus_path = Path(artifacts["consensus_path"])
    conflicts_path = Path(artifacts["conflicts_path"])
    write_json(consensus_path, consensus)
    write_json(conflicts_path, consensus["conflicts"])

    adjudication_path = Path(artifacts["adjudication_path"])
    conflicts = consensus.get("conflicts") or {}
    adjudication: dict[str, Any] | None = None
    if conflicts and arbiter_model in models:
        adjudication = {
            "schema_version": ANALYSIS_MODULE_B_VERSION,
            "decisions": {
                field_path: {
                    "value": None,
                    "decision": "needs_review",
                    "evidence": "",
                    "confidence": 0.0,
                    "validation": "arbiter_model_not_independent",
                }
                for field_path in conflicts
            },
            "needs_review": sorted(conflicts),
            "ignored_fields": [],
            "skipped": "arbiter_model_not_independent",
        }
        write_json(
            adjudication_path,
            {
                "schema_version": ANALYSIS_MODULE_B_VERSION,
                "model": arbiter_model,
                "input_sha256": input_sha256,
                "completed_at": utc_now_iso(),
                "skipped": True,
                "result": adjudication,
            },
        )
    elif conflicts:
        cached_adjudication = None
        if adjudication_path.exists():
            try:
                candidate = load_json(adjudication_path)
            except (OSError, json.JSONDecodeError):
                candidate = None
            if (
                isinstance(candidate, dict)
                and candidate.get("model") == arbiter_model
                and candidate.get("input_sha256") == input_sha256
                and isinstance(candidate.get("result"), dict)
            ):
                cached_adjudication = candidate["result"]
        if cached_adjudication is not None:
            adjudication = cached_adjudication
        else:
            try:
                prompt = build_adjudication_prompt(
                    item_id=item_id,
                    consensus=consensus,
                    candidates=candidates,
                    source_text=evidence_text,
                    profile=active_adapter.analysis_profile,
                )
                raw_adjudication = llm_helper.chat_with_glm(prompt, model=arbiter_model)
                adjudication = validate_adjudication(
                    raw_adjudication,
                    consensus=consensus,
                    source_text=evidence_text,
                    profile=active_adapter.analysis_profile,
                )
            except Exception as exc:
                receipt = {
                    **base_receipt,
                    "status": "adjudication_failed",
                    "candidate_success_count": 3,
                    "consensus_stats": consensus.get("stats") or {},
                    "error": _safe_module_b_error(exc),
                }
                write_json(receipt_path, receipt)
                write_json(latest_path, receipt)
                return receipt
            write_json(
                adjudication_path,
                {
                    "schema_version": ANALYSIS_MODULE_B_VERSION,
                    "model": arbiter_model,
                    "input_sha256": input_sha256,
                    "completed_at": utc_now_iso(),
                    "result": adjudication,
                },
            )
    else:
        adjudication = {
            "schema_version": ANALYSIS_MODULE_B_VERSION,
            "decisions": {},
            "needs_review": [],
            "ignored_fields": [],
            "skipped": "all_fields_locked_by_consensus",
        }
        write_json(
            adjudication_path,
            {
                "schema_version": ANALYSIS_MODULE_B_VERSION,
                "model": None,
                "input_sha256": input_sha256,
                "completed_at": utc_now_iso(),
                "result": adjudication,
            },
        )

    if conflicts and arbiter_model in models:
        # Shadow mode may use a placeholder candidate route in configuration,
        # but calling it again would add cost without independent evidence.
        adjudication = dict(adjudication or {})
        needs_review = list(adjudication.get("needs_review") or [])
        independence_gate = "analysis_module_b.arbiter_model_not_independent"
        if independence_gate not in needs_review:
            needs_review.append(independence_gate)
        adjudication["needs_review"] = sorted(needs_review)
        quality_gates = dict(adjudication.get("quality_gates") or {})
        quality_gates["arbiter_model_independent"] = False
        adjudication["quality_gates"] = quality_gates

    final_payload = compose_final_payload(
        consensus=consensus,
        adjudication=adjudication,
        profile=active_adapter.analysis_profile,
    )
    final_payload[ANALYSIS_PROVENANCE_FIELD] = dict(analysis_provenance)
    status = final_status(adjudication)
    write_json(Path(artifacts["final_path"]), final_payload)
    receipt = {
        **base_receipt,
        "status": status,
        "candidate_success_count": 3,
        "consensus_stats": consensus.get("stats") or {},
        "needs_review": adjudication.get("needs_review") or [],
        "completed_at": utc_now_iso(),
    }
    write_json(receipt_path, receipt)
    write_json(latest_path, receipt)
    return {**receipt, "final_payload": final_payload}

__all__ = ('ANALYSIS_MODULE_B_DEFAULT_MODELS', 'ANALYSIS_MODULE_B_DEFAULT_ARBITER', 'ANALYSIS_PROVENANCE_FIELD', 'AnalysisModuleBIncompleteError', '_analysis_module_b_mode', '_analysis_module_b_models', '_analysis_module_b_arbiter_model', '_analysis_module_b_parallelism', '_analysis_module_b_candidate_attempts', '_analysis_module_b_candidate_retry_seconds', '_analysis_module_b_retryable_candidate_error', '_analysis_module_b_shadow_sample_rate', '_analysis_module_b_shadow_selected', '_safe_module_b_error', '_module_b_cached_candidate', '_run_analysis_module_b')
