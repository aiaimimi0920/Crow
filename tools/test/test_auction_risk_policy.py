"""Risk alias, exact-boolean and result callback contracts on both entrypoints."""

import pytest


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_collection_operations

    return server if request.param else server_collection_operations


def test_entrypoints_have_explicit_native_owner(host):
    from src.collection.adapters.auction_risks import AuctionRiskPolicy

    for name in AuctionRiskPolicy.__all__:
        assert isinstance(getattr(host, name).__self__, AuctionRiskPolicy)
        if host.__name__ == "src.server":
            assert getattr(host._CONTEXT, name) is getattr(host, name)


def test_payload_shape_and_top_level_precedence(host):
    for payload in (None, [], "invalid", False):
        assert host._get_risk_payload({"avm_risk_features": payload}) == {}
    payload = {"flag": True}
    item = {"avm_risk_features": payload, "flag": None}
    assert host._get_risk_payload(item) is payload
    assert host._risk_value(item, "flag") is True
    for value in (False, 0, ""):
        item["flag"] = value
        assert host._risk_value(item, "flag") == value


def test_alias_sync_preserves_existing_values_and_identity(host, monkeypatch):
    monkeypatch.setattr(host, "RISK_ALIAS_KEYS", ["a", "b", "c", "d", "e"])
    item = {
        "a": None,
        "b": False,
        "所属小区": "",
        "housing_type": "",
        "avm_risk_features": {
            "a": True,
            "b": True,
            "c": 0,
            "d": "",
            "e": None,
            "community_name": "小区",
            "housing_type": "住宅",
        },
    }
    assert host.sync_avm_risk_aliases(item) is item
    assert item["a"] is None and item["b"] is False
    assert item["c"] == 0 and "d" not in item and "e" not in item
    assert item["所属小区"] == "小区" and item["housing_type"] == "住宅"
    item["所属小区"] = "保留"
    host.sync_avm_risk_aliases(item)
    assert item["所属小区"] == "保留"


def test_signals_require_exact_booleans_and_preserve_label_order(host, monkeypatch):
    monkeypatch.setattr(host, "MALIGNANT_RISK_LABELS", {"second": "B", "first": "A"})
    assert host.extract_risk_signals(
        {
            "second": True,
            "first": True,
            "clear_delivery": False,
            "land_right_type": "划拨",
        }
    ) == ["B", "A", "法院不负责清场交付", "土地性质为划拨"]
    assert (
        host.extract_risk_signals(
            {
                "second": 1,
                "first": "true",
                "clear_delivery": 0,
            }
        )
        == []
    )


def test_saved_helpers_read_replaced_callbacks_and_constants(host, monkeypatch):
    value, sync, signals = (
        host._risk_value,
        host.sync_avm_risk_aliases,
        host.extract_risk_signals,
    )
    monkeypatch.setattr(host, "_get_risk_payload", lambda item: {"new": True})
    assert value({}, "new") is True
    monkeypatch.setattr(host, "RISK_ALIAS_KEYS", ["new"])
    assert sync({}) == {"new": True}
    monkeypatch.setattr(host, "MALIGNANT_RISK_LABELS", {"new": "current"})
    monkeypatch.setattr(host, "_risk_value", lambda item, key: key == "new" or None)
    assert signals({}) == ["current"]


@pytest.mark.parametrize("risks", [[], ["A", "B"]])
def test_result_uses_live_callbacks_and_preserves_response(host, monkeypatch, risks):
    saved = host.build_avm_result
    calls = []
    monkeypatch.setattr(
        host, "get_predicted_price", lambda item: calls.append("predicted") or 100
    )
    monkeypatch.setattr(
        host, "get_starting_price", lambda item: calls.append("starting") or 60
    )

    def margin(predicted, starting):
        assert (predicted, starting) == (100, 60)
        calls.append("margin")
        return 0.4

    monkeypatch.setattr(host, "compute_margin", margin)
    monkeypatch.setattr(
        host, "extract_risk_signals", lambda item: calls.append("risks") or risks
    )
    assert saved(123, {}) == {
        "id": "123",
        "predicted_price": 100,
        "starting_price": 60,
        "margin": 0.4,
        "is_malignant_risk": bool(risks),
        "major_risks": risks,
        "risk_summary": "；".join(risks) if risks else "未发现恶性风控标签",
    }
    assert calls == ["predicted", "starting", "margin", "risks"]
