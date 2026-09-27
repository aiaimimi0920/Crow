from __future__ import annotations

from src import llm_openai_compatible
from tools.test.analysis_module_b_integration_test_context import *


def test_shadow_mode_keeps_module_a_as_official_result(tmp_path: Path, monkeypatch) -> None:
    item_dir, seed, _html = _write_raw_item(tmp_path, "module-b-shadow")

    def _module_a(_content: str, item_id: str | None = None) -> str:
        assert item_id == "module-b-shadow"
        return json.dumps(
            {
                "标题": seed["title"],
                "完整地址": "北京市东城区测试小区1号房",
                "成交价格": 1_000_000,
                "起拍价格": 800_000,
                "建筑面积": 80,
            },
            ensure_ascii=False,
        )

    def _module_b(**_kwargs):
        provenance = {
            "module": "B",
            "pipeline_version": "analysis_module_b_v1",
            "run_id": "c" * 64,
            "input_sha256": "d" * 64,
            "model_routing_sha256": "b" * 64,
        }
        return {
            "schema_version": "analysis_module_b_v1",
            "run_id": "c" * 64,
            "input_sha256": "d" * 64,
            "mode": "shadow",
            "status": "finalized",
            "analysis_provenance": provenance,
            "final_payload": {"建筑面积": 99, "analysis_provenance": provenance},
        }

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_MODE", "shadow")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE", "1")
    monkeypatch.setattr(llm_helper, "extract_auction_data", _module_a)
    monkeypatch.setattr(live_batch_smoke, "_run_analysis_module_b", _module_b)

    selected = live_batch_smoke.analyze_raw_item("module-b-shadow", output_dir=tmp_path)

    extracted = live_batch_smoke.load_json(item_dir / "extracted.json")
    assert extracted["建筑面积"] == 80
    assert "analysis_provenance" not in extracted
    assert "analysis_provenance" not in live_batch_smoke.load_json(item_dir / "final.json")
    assert selected["analysis_module_b"]["status"] == "finalized"
    assert selected["analysis_module_b"]["analysis_provenance"]["module"] == "B"
    assert "final_payload" not in selected["analysis_module_b"]


def test_shadow_sampling_can_skip_module_b_without_skipping_module_a(tmp_path: Path, monkeypatch) -> None:
    item_dir, seed, _html = _write_raw_item(tmp_path, "module-b-sampled-out")

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_MODE", "shadow")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE", "0")
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *_args, **_kwargs: json.dumps(
            {"标题": seed["title"], "建筑面积": 80}, ensure_ascii=False
        ),
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "_run_analysis_module_b",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("sampled-out shadow items must not call module B")
        ),
    )

    selected = live_batch_smoke.analyze_raw_item("module-b-sampled-out", output_dir=tmp_path)

    assert (item_dir / "final.json").is_file()
    assert selected["analysis_module_b"]["status"] == "sampled_out"
    assert selected["analysis_module_b"]["shadow_sample_rate"] == 0


def test_shadow_sampling_defaults_to_one_percent(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE", raising=False)

    assert live_batch_smoke._analysis_module_b_shadow_sample_rate() == 0.01


def test_primary_mode_publishes_finalized_module_b_without_running_module_a(tmp_path: Path, monkeypatch) -> None:
    item_dir, _seed, _html = _write_raw_item(tmp_path, "module-b-primary")
    provenance = {
        "module": "B",
        "pipeline_version": "analysis_module_b_v1",
        "run_id": "e" * 64,
        "input_sha256": "f" * 64,
        "model_routing_sha256": "a" * 64,
    }

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_MODE", "primary")
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("module A must not run when module B is primary")
        ),
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "_run_analysis_module_b",
        lambda **_kwargs: {
            "schema_version": "analysis_module_b_v1",
            "run_id": "e" * 64,
            "item_id": "module-b-primary",
            "input_sha256": "f" * 64,
            "mode": "primary",
            "status": "finalized",
            "candidate_models": ["flash", "pro", "grok"],
            "arbiter_model": "arbiter",
            "arbiter_independent_model": True,
            "analysis_provenance": provenance,
            "artifacts": {"receipt_path": str(item_dir / "analysis-b" / "receipt.json")},
            "final_payload": {
                "完整地址": "北京市东城区测试小区1号房",
                "成交价格": 1_000_000,
                "起拍价格": 800_000,
                "建筑面积": 81,
                "analysis_provenance": provenance,
            },
        },
    )

    selected = live_batch_smoke.analyze_raw_item("module-b-primary", output_dir=tmp_path)

    extracted = live_batch_smoke.load_json(item_dir / "extracted.json")
    assert extracted["建筑面积"] == 81
    assert extracted["analysis_provenance"] == provenance
    assert live_batch_smoke.load_json(item_dir / "final.json")["analysis_provenance"] == provenance
    assert selected["analysis_module_b"]["status"] == "finalized"
    assert selected["analysis_module_b"]["analysis_provenance"] == provenance
    assert "final_payload" not in selected["analysis_module_b"]
    assert (item_dir / "final.json").is_file()


def test_primary_mode_refuses_incomplete_module_b_without_writing_official_result(tmp_path: Path, monkeypatch) -> None:
    item_dir, _seed, _html = _write_raw_item(tmp_path, "module-b-primary-partial")

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_MODE", "primary")
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("module A must not run when module B is primary")
        ),
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "_run_analysis_module_b",
        lambda **_kwargs: {
            "schema_version": "analysis_module_b_v1",
            "run_id": "1" * 64,
            "item_id": "module-b-primary-partial",
            "input_sha256": "2" * 64,
            "mode": "primary",
            "status": "candidate_partial",
            "candidate_models": ["flash", "pro", "grok"],
            "artifacts": {},
        },
    )

    try:
        live_batch_smoke.analyze_raw_item("module-b-primary-partial", output_dir=tmp_path)
    except live_batch_smoke.AnalysisModuleBIncompleteError as exc:
        assert "candidate_partial" in str(exc)
    else:
        raise AssertionError("primary mode must reject incomplete module B output")

    assert not (item_dir / "extracted.json").exists()
    assert not (item_dir / "final.json").exists()


def test_explicit_openai_compatible_model_disables_candidate_fallback(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        llm_openai_compatible,
        "_get_openai_compatible_config",
        lambda: {
            "base_url": "http://127.0.0.1:1/v1",
            "api_key": "test",
            "model": "primary",
            "models": ["primary", "fallback"],
            "timeout": 1,
            "max_retries": 1,
        },
    )

    def _chat(_content, config):
        captured.update(config)
        return '{"ok":true}'

    monkeypatch.setattr(llm_openai_compatible, "_chat_with_openai_compatible", _chat)

    assert llm_helper.chat_with_glm("test", model="grok-4.6") == '{"ok":true}'
    assert captured["model"] == "grok-4.6"
    assert captured["models"] == ["grok-4.6"]


def test_pc2_module_b_is_default_off_and_uses_only_explicit_non_gpt_routes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "ops" / "pc2-linux" / "compose.yaml").read_text(encoding="utf-8")
    env_example = (repo_root / "ops" / "pc2-linux" / "env.example").read_text(encoding="utf-8")

    assert "FAPAI_ANALYSIS_MODULE_B_MODE: ${FAPAI_ANALYSIS_MODULE_B_MODE:-off}" in compose
    assert "FAPAI_ANALYSIS_MODULE_B_MODE=off" in env_example
    assert (
        "FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS="
        "DeepSeek-V4-Flash,DeepSeek-V4-Pro-0813,gemini-3.1-flash"
    ) in env_example
    assert "FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL=grok-4.6" in env_example
    assert "FAPAI_ANALYSIS_MODULE_B_CANDIDATE_ATTEMPTS=3" in env_example
    assert "FAPAI_ANALYSIS_MODULE_B_CANDIDATE_RETRY_SECONDS=10" in env_example
    primary_model_line = next(line for line in env_example.splitlines() if line.startswith("OPENAI_MODEL="))
    assert "gpt" not in primary_model_line.lower()
