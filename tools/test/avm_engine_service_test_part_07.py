from tools.test.avm_engine_service_test_context import *  # noqa: F401,F403


def test_avm_service_build_feature_dataset_uses_repository_feature_rows_without_canonical_mapper(
    monkeypatch,
):
    class _FakeRepo:
        enabled = True

        def yield_feature_source_rows(
            self, limit: int | None = None, chunk_size: int = 1000
        ):
            yield {
                "item_id": "repo-1",
                "auction_date": "2026-01-01 10:00:00",
                "province": "上海市",
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "business_area": "张江",
                "area_sqm": 100.0,
                "starting_price": 800000.0,
                "transaction_price": 1000000.0,
                "actual_paid_price": 1000000.0,
                "latitude": 31.2,
                "longitude": 121.5,
                "status": "done",
                "housing_type": "住宅",
            }

        def dataset_signature(self):
            return (1, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_map(_value):
        raise AssertionError(
            "repository feature rows should bypass map_raw_to_canonical"
        )

    monkeypatch.setattr("src.avm.service_data.map_raw_to_canonical", _forbidden_map)

    dataset = service._build_feature_dataset()

    assert len(dataset) == 1
    assert dataset[0]["item_id"] == "repo-1"


def test_avm_service_predict_by_item_data_uses_repository_candidate_rows_without_full_dataset(
    monkeypatch,
):
    class _FakeRepo:
        enabled = True

        def build_coordinate_centroids(self):
            return {"community::测试小区": (31.2, 121.5)}

        def iter_feature_candidate_rows(self, subject, **kwargs):
            return [
                {
                    "item_id": "repo-2",
                    "auction_date": "2026-02-01 10:00:00",
                    "province": "上海市",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "business_area": "张江",
                    "area_sqm": 100.0,
                    "starting_price": 900000.0,
                    "transaction_price": 1100000.0,
                    "actual_paid_price": 1100000.0,
                    "latitude": 31.2,
                    "longitude": 121.5,
                    "status": "done",
                    "housing_type": "住宅",
                }
            ]

        def dataset_signature(self):
            return (2, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_build():
        raise AssertionError(
            "predict_by_item_data fast path should not build full feature dataset"
        )

    monkeypatch.setattr(service, "_build_feature_dataset", _forbidden_build)

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

    assert result["trace"]["candidate_source"] == "repository_candidates"
    assert result["trace"]["candidate_pool_size"] == 1


def test_avm_service_predict_by_item_data_prefers_repository_analysis_candidate_rows(
    monkeypatch,
):
    class _FakeRepo:
        enabled = True

        def build_coordinate_centroids(self):
            return {"community::测试小区": (31.2, 121.5)}

        def iter_analysis_candidate_rows(self, subject, **kwargs):
            return [
                {
                    "item_id": "repo-analysis-1",
                    "auction_date": "2026-02-01 10:00:00",
                    "province": "上海市",
                    "city": "上海市",
                    "district": "浦东新区",
                    "community_name": "测试小区",
                    "business_area": "张江",
                    "area_sqm": 100.0,
                    "starting_price": 900000.0,
                    "transaction_price": 1100000.0,
                    "actual_paid_price": 1100000.0,
                    "latitude": 31.2,
                    "longitude": 121.5,
                    "status": "done",
                    "housing_type": "住宅",
                }
            ]

        def iter_feature_candidate_rows(self, subject, **kwargs):
            raise AssertionError("analysis candidate fast path should take precedence")

        def dataset_signature(self):
            return (2, "2026-05-12 00:00:00")

    service = AVMService(data_dir="unused", repository=_FakeRepo())

    def _forbidden_build():
        raise AssertionError(
            "repository analysis candidate fast path should not build full feature dataset"
        )

    monkeypatch.setattr(service, "_build_feature_dataset", _forbidden_build)

    result = service.predict_by_item_data(
        {
            "id": "subject-analysis-1",
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

    assert result["trace"]["candidate_source"] == "repository_analysis_candidates"
    assert result["trace"]["candidate_pool_size"] == 1
