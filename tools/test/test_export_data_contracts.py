"""Keep property data usable while checking actual credential/export boundaries."""

import json

import pytest

from tools import live_smoke_resume as resume
from tools import live_smoke_runtime as runtime
from tools.build_avm_features import build_avm_features
from tools.live_smoke_context import LiveSmokeConfig

pytestmark = pytest.mark.security


@pytest.mark.parametrize("has_keys", [True, False, None])
def test_avm_export_projects_property_coordinates_and_excludes_credentials(
    tmp_path, has_keys
):
    record = {
        "item_id": "synthetic-property-01",
        "auction_date": "2026-01-01",
        "latitude": 12.34,
        "longitude": 56.78,
        "area_sqm": 100,
        "transaction_price": 200000,
        "has_keys": has_keys,
        "api_key": "synthetic-api-credential",
        "password": "synthetic-password-credential",
        "cookies": [{"name": "sid", "value": "synthetic-session-credential"}],
        "credentials": {"token": "synthetic-nested-credential"},
    }
    canonical = tmp_path / "canonical.jsonl"
    canonical.write_text(json.dumps(record) + "\n", encoding="utf-8")
    output = tmp_path / "features.jsonl"
    stats = tmp_path / "stats.json"
    result = build_avm_features(str(canonical), str(output), str(stats))
    feature = json.loads(output.read_text(encoding="utf-8"))
    assert feature["has_keys"] is has_keys  # Court possession of physical keys.
    assert feature["latitude"] == 12.34
    assert feature["longitude"] == 56.78
    assert feature["unit_price"] == 2000
    assert feature["item_id"] == record["item_id"]
    assert {"api_key", "password", "cookies", "credentials"}.isdisjoint(feature)
    assert "credential" not in output.read_text(encoding="utf-8")
    assert result["stats"]["total_records"] == 1
    assert result["stats"]["non_null"]["latitude"] == 1
    assert result["stats"]["non_null"]["longitude"] == 1


def test_live_smoke_audit_round_trip_preserves_domain_data_and_identifiers(tmp_path):
    # The audit writer intentionally serializes domain evidence, not a sanitized
    # public API response; do not remove geographic features or key-named IDs.
    record = {
        "id": "synthetic-property-01",
        "location": {"latitude": 12.34, "longitude": 56.78},
        "property": {"has_keys": False, "is_occupied": None},
        "community_stable_key": "synthetic::community",
        "trusted_seed": {"title": "合成测试拍品", "currentPrice": 200000},
        "source_url": "https://auction.example.invalid/item/01",
    }
    path = tmp_path / "item" / "final.json"
    resume.write_json(path, record)
    assert resume.load_json(path) == record


def test_live_smoke_empty_summary_exports_cookie_count_not_cookie_values(
    tmp_path, monkeypatch, capsys
):
    cookies = [{"name": "sid", "value": "synthetic-session-credential"}]
    monkeypatch.setattr(runtime, "_browserless_seed_probe", lambda: object())
    monkeypatch.setattr(runtime, "export_cookies", lambda _endpoint: cookies)
    sessions = []
    monkeypatch.setattr(
        runtime, "build_http", lambda supplied: sessions.append(supplied)
    )
    monkeypatch.setattr(
        runtime,
        "collect_list_union",
        lambda *_args: {
            "items": [],
            "list_union": {},
            "first_fetch": {"list_item_count": 0},
        },
    )
    config = LiveSmokeConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://auction.example.invalid/list",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        raw_only=True,
    )
    assert runtime.run_live_smoke(config) == 1
    assert sessions == [cookies]
    summary = resume.load_json(tmp_path / "summary.json")
    assert summary["cookie_count"] == 1
    for path in tmp_path.rglob("*.json"):
        assert "synthetic-session-credential" not in path.read_text(encoding="utf-8")
    assert "synthetic-session-credential" not in capsys.readouterr().out
