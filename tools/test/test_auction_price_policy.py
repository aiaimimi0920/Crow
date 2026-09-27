"""Legacy auction numeric semantics used by seed and AVM facade callbacks."""

import pytest


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_collection_operations

    return server if request.param else server_collection_operations


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        (0, 0.0),
        (-2, -2.0),
        (True, 1.0),
        ([], None),
        ("", None),
        ("无", None),
        ("1,234.50元", 1234.5),
        ("2.5万", 25000.0),
        ("2万元", 20000.0),
        ("1.2亿", 120000000.0),
        ("-2", 2.0),
        ("1e3", 13.0),
        ("1.2.3", None),
    ],
)
def test_price_parsing_preserves_legacy_contract(host, raw, expected):
    assert host.parse_price(raw) == expected


def test_price_field_precedence_and_zero_fallback(host):
    assert host.get_starting_price({"starting_price": 0, "起拍价格": "2万"}) == 20000
    assert (
        host.get_predicted_price(
            {"predicted_price": 0, "估值": 12, "evaluation_price": 20}
        )
        == 12
    )
    assert (
        host.get_predicted_price({"evaluation_price": "4", "transaction_price": 7}) == 4
    )
    assert host.get_predicted_price({"成交价格": 9}) == 9
    assert host.get_predicted_price({}) is None


def test_margin_and_integer_boundaries(host):
    assert host.compute_margin(100, 60) == 0.4
    assert host.compute_margin(100, 0) == 1
    assert host.compute_margin(100, 120) == -0.2
    for predicted, starting in [(0, 1), (-1, 0), (None, 1), (1, None)]:
        assert host.compute_margin(predicted, starting) is None
    assert host._safe_int("1.9万") == 19000
    assert host._safe_int(-1.9) == -1
    assert host._safe_int(float("nan")) is None
    with pytest.raises(OverflowError):
        host._safe_int(float("inf"))


def test_saved_composite_helpers_use_current_parser(host, monkeypatch):
    from src.collection.adapters.auction_prices import AuctionPricePolicy

    for name in AuctionPricePolicy.__all__:
        assert isinstance(getattr(host, name).__self__, AuctionPricePolicy)
        if host.__name__ == "src.server":
            assert getattr(host._CONTEXT, name) is getattr(host, name)
    starting, predicted, integer = (
        host.get_starting_price,
        host.get_predicted_price,
        host._safe_int,
    )
    monkeypatch.setattr(
        host, "parse_price", lambda value: 8.9 if value == "chosen" else None
    )
    assert starting({"starting_price": "chosen"}) == 8.9
    assert predicted({"transaction_price": "chosen"}) == 8.9
    assert integer("chosen") == 8
