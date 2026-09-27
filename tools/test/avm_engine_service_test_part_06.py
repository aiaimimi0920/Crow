from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


def test_predict_by_item_id_surfaces_risk_validation_and_review_reason(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "4701",
            "url": "https://x/4701",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        {
            "id": "4702",
            "url": "https://x/4702",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2001,
            "经度": 121.5001,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    service = AVMService(data_dir=str(data_dir))
    result = service.predict_by_item_id("4701")

    assert result["risk_validation"]["ok"] is False
    assert result["risk_validation"]["missing_required_count"] > 0
    assert "risk_feature_incomplete" in result["manual_review_reasons"]
    assert result["manual_review_recommended"] is True


def test_avm_service_fills_missing_subject_coordinates_from_centroid(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "2001",
            "url": "https://x/2001",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
        {
            "id": "2002",
            "url": "https://x/2002",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.200001,
            "经度": 121.500001,
        },
        {
            "id": "2003",
            "url": "https://x/2003",
            "成交价格": "120万",
            "起拍价格": "100万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.200101,
            "经度": 121.500101,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    service = AVMService(data_dir=str(data_dir))
    result = service.predict_by_item_id("2001")

    assert result["predicted_price"] is not None
    assert result["trace"]["subject_coordinate_strategy"] == "community_centroid"


def test_avm_service_predict_by_item_id_uses_repository_subject_without_file_scan(
    monkeypatch,
):
    class _FakeRepo:
        enabled = True

        def __init__(self):
            self.lookup_calls = 0

        def get_flat_item(self, item_id: str):
            self.lookup_calls += 1
            if item_id == "repo-1":
                return {
                    "item_id": "repo-1",
                    "source_url": "https://x/repo-1",
                    "transaction_price": 1000000.0,
                    "starting_price": 800000.0,
                    "area_sqm": 100.0,
                    "auction_date": "2026-01-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "housing_type": "住宅",
                }
            return None

        def iter_flat_items(self, limit: int | None = None):
            return [
                {
                    "item_id": "repo-1",
                    "source_url": "https://x/repo-1",
                    "transaction_price": 1000000.0,
                    "starting_price": 800000.0,
                    "area_sqm": 100.0,
                    "auction_date": "2026-01-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "housing_type": "住宅",
                },
                {
                    "item_id": "repo-2",
                    "source_url": "https://x/repo-2",
                    "transaction_price": 1100000.0,
                    "starting_price": 900000.0,
                    "area_sqm": 100.0,
                    "auction_date": "2026-02-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "housing_type": "住宅",
                },
            ]

        def dataset_signature(self):
            return (2, "2026-05-12 00:00:00")

    repo = _FakeRepo()
    service = AVMService(data_dir="unused", repository=repo)
    monkeypatch.setattr(
        service,
        "_iter_data_files",
        lambda: (_ for _ in ()).throw(RuntimeError("file scan should not happen")),
    )

    result = service.predict_by_item_id("repo-1")

    assert result["item_id"] == "repo-1"
    assert result["comparable_count"] == 1
    assert repo.lookup_calls == 1


def test_avm_service_ensure_coordinate_cache_uses_canonical_rows_without_feature_build(
    monkeypatch,
):
    class _FakeRepo:
        enabled = True

        def yield_coordinate_rows(self, chunk_size: int = 1000):
            yield {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "latitude": 31.2,
                "longitude": 121.5,
            }

        def yield_flat_items(self, limit: int | None = None, chunk_size: int = 1000):
            yield {
                "item_id": "coord-1",
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "latitude": 31.2,
                "longitude": 121.5,
            }

        def dataset_signature(self):
            return (1, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_build_features(_value):
        raise AssertionError("ensure_coordinate_cache should not call build_features")

    monkeypatch.setattr(
        "src.avm.service_data.build_features", _forbidden_build_features
    )

    centroids = service.ensure_coordinate_cache()

    assert centroids["community::测试小区"] == (31.2, 121.5)


def test_avm_service_health_snapshot_lightweight_does_not_build_dataset(monkeypatch):
    service = AVMService(data_dir="unused", repository=None)

    def _forbidden_build():
        raise AssertionError(
            "lightweight health snapshot should not build feature dataset when cache is empty"
        )

    monkeypatch.setattr(service, "_build_feature_dataset", _forbidden_build)

    health = service.health_snapshot(lightweight=True)

    assert health["dataset_size"] == 0
    assert health["risk_validation_counts"] == {"ok": 0, "incomplete": 0, "invalid": 0}
    assert health["risk_feature_completeness_avg"] == 0.0
    assert health["feature_cache_ready"] is False
    assert health["model_version"] == service.model_version()


def test_avm_service_health_snapshot_surfaces_risk_validation_summary(tmp_path: Path):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "4801",
            "url": "https://x/4801",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
            "housing_type": "住宅",
            "is_occupied": False,
            "has_long_lease": False,
            "clear_delivery": True,
            "tax_burden": "各自承担",
            "is_fractional_share": False,
            "build_year": 2010,
            "total_floors": 18,
            "floor_level": "中区",
            "has_elevator": True,
            "orientation": "南",
            "land_right_type": "出让",
            "is_haunted": False,
            "has_keys": True,
            "property_fee_owed": False,
            "special_school_tag": False,
            "evaluation_price": 1000000,
            "layout": "2室1厅1卫",
            "is_restricted_purchase": False,
            "includes_parking": False,
            "tax_is_company_owned": False,
            "has_lease_before_mortgage": False,
        },
        {
            "id": "4802",
            "url": "https://x/4802",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-02-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2001,
            "经度": 121.5001,
        },
    ]
    (data_dir / "2026-01-01.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=False)

    assert health["dataset_size"] == 2
    assert health["risk_validation_counts"]["ok"] == 1
    assert health["risk_validation_counts"]["incomplete"] == 1
    assert health["risk_validation_counts"]["invalid"] == 0
    assert 0.0 < health["risk_feature_completeness_avg"] < 1.0


def test_avm_service_health_snapshot_surfaces_active_risk_factor_overrides(
    tmp_path: Path, monkeypatch
):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    (data_dir / "2026-01-01.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "src.avm.engine.AVM_CONFIG_MANAGER.get_config",
        lambda: {"risk_factor_overrides": {"is_occupied": 0.5}},
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=True)

    assert health["active_risk_factor_override_count"] == 1
    assert health["active_risk_factor_overrides"]["is_occupied"] == 0.5


def test_avm_service_health_snapshot_surfaces_active_weighting(
    tmp_path: Path, monkeypatch
):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    (data_dir / "2026-01-01.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "src.avm.service_health.get_effective_weighting",
        lambda defaults=None: {
            "distance_power": 1.7,
            "time_decay": 0.8,
            "community_boost": 2.2,
        },
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=True)

    assert health["active_weighting"]["distance_power"] == 1.7
    assert health["active_weighting"]["community_boost"] == 2.2


def test_avm_service_health_snapshot_surfaces_active_risk_discount_factor(
    tmp_path: Path, monkeypatch
):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    (data_dir / "2026-01-01.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        "src.avm.service_health.get_effective_risk_discount_factor",
        lambda default=0.9: 0.45,
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=True)

    assert health["active_risk_discount_factor"] == 0.45


def test_avm_service_health_snapshot_surfaces_coordinate_strategy_counts(
    tmp_path: Path,
):
    data_dir = tmp_path / "datas"
    data_dir.mkdir()
    payload = [
        {
            "id": "1",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        {
            "id": "2",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "交易时间": "2026-01-02 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
        },
    ]
    (data_dir / "2026-01-01.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    service = AVMService(data_dir=str(data_dir))
    health = service.health_snapshot(lightweight=False)

    assert health["coordinate_strategy_counts"]["observed"] == 1
    assert health["coordinate_strategy_counts"]["community_centroid"] == 1


def test_avm_service_limits_candidate_pool_for_large_dataset(monkeypatch):
    service = AVMService(data_dir="unused", repository=None)
    dataset = []
    for index in range(6001):
        dataset.append(
            {
                "item_id": f"comp-{index}",
                "auction_date": f"2026-03-{(index % 28) + 1:02d} 10:00:00",
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "business_area": "张江",
                "area_sqm": 100.0,
                "starting_price": 800000.0,
                "transaction_price": 1000000.0 + index,
                "actual_paid_price": 1000000.0 + index,
                "unit_price": 10000.0,
                "housing_type": "住宅",
            }
        )

    monkeypatch.setattr(service, "_dataset_signature", lambda: ("test", 1))
    monkeypatch.setattr(service, "_build_feature_dataset", lambda: dataset)
    monkeypatch.setattr(service, "_centroid_cache", {})

    captured = {}

    def _fake_predict(subject, comparables):
        captured["count"] = len(list(comparables))
        return {
            "predicted_price": 1000000.0,
            "predicted_unit_price": 10000.0,
            "confidence": 0.5,
            "comparable_count": captured["count"],
            "strategy": "city_fallback",
            "trace": {},
            "top_factors": [],
        }

    monkeypatch.setattr("src.avm.service_prediction.predict_fair_price", _fake_predict)

    result = service.predict_by_item_data(
        {
            "id": "subject-1",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "交易时间": "2026-03-01 10:00:00",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "最靠近商圈": "张江",
            "housing_type": "住宅",
        }
    )

    assert captured["count"] == 5000
    assert result["trace"]["candidate_pool_size"] == 5000
