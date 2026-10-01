"""geocoding 服务商适配与坐标系转换。

关键正确性问题：国内 geocoding 服务返回的不是 WGS-84。

- 高德返回 GCJ-02（火星坐标，国测局加密偏移）
- 百度返回 BD-09（在 GCJ-02 上再叠一层偏移）
- `property_listing.geom` 声明的是 SRID 4326，即 WGS-84

直接把 GCJ-02 当 WGS-84 存进去，会带来 50-500 米的系统性偏移。对「同小区比价」
影响不大（同区域内点位整体同向平移），但一旦参与距离计算、半径筛选或跨源
坐标比对就会出错。所以入库前必须转换。

这一层不发真实请求，全部用 mock，可以在拿到 key 之前测完。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------- 坐标系转换 ----------


def test_wgs84_to_gcj02_matches_known_beijing_reference() -> None:
    """用已知参考点锚定算法正确性。

    北京天安门 WGS-84 (39.9087, 116.3975) 对应 GCJ-02 约 (39.9100, 116.4038)。
    这是公开可查的对照值，用它保证偏移算法没写错。
    """
    from tools.geocode_client import wgs84_to_gcj02

    lat, lon = wgs84_to_gcj02(39.9087, 116.3975)

    assert abs(lat - 39.9100) < 0.0005
    assert abs(lon - 116.4038) < 0.0005


def test_gcj02_to_wgs84_shifts_longitude_west() -> None:
    """经度方向是稳定的：GCJ-02 在 WGS-84 以东，所以反向转换必然西移。

    纬度方向不稳定——实测北京 +0.0014、上海 -0.0019，随位置变号，
    所以这里只对纬度断言偏移量级，不断言方向。
    """
    from tools.geocode_client import gcj02_to_wgs84

    lat, lon = gcj02_to_wgs84(31.2304, 121.4737)

    assert lon < 121.4737
    assert 0.001 < (121.4737 - lon) < 0.01
    assert 0.0001 < abs(31.2304 - lat) < 0.01


def test_gcj02_to_wgs84_is_approximately_reversible() -> None:
    from tools.geocode_client import gcj02_to_wgs84, wgs84_to_gcj02

    original = (39.9087, 116.3975)  # 北京天安门
    gcj = wgs84_to_gcj02(*original)
    back = gcj02_to_wgs84(*gcj)

    # 往返误差应远小于偏移本身（< 10 米 ≈ 0.0001 度）
    assert abs(back[0] - original[0]) < 0.0001
    assert abs(back[1] - original[1]) < 0.0001


def test_coordinates_outside_china_are_not_shifted() -> None:
    """GCJ-02 偏移只在国境内生效，境外坐标必须原样返回。"""
    from tools.geocode_client import gcj02_to_wgs84

    # 东京
    lat, lon = gcj02_to_wgs84(35.6762, 139.6503)

    assert lat == 35.6762
    assert lon == 139.6503


def test_bd09_to_wgs84_goes_through_gcj02() -> None:
    from tools.geocode_client import bd09_to_wgs84

    # BD-09 偏移比 GCJ-02 更大，转换后应向西南移动更多
    lat, lon = bd09_to_wgs84(31.2364, 121.4801)

    assert lat < 31.2364
    assert lon < 121.4801
    # BD-09 -> WGS84 总偏移通常在 0.003-0.02 度
    assert 0.002 < (31.2364 - lat) < 0.03


# ---------- 高德响应解析 ----------


def _amap_ok_body(lon: str = "121.4737", lat: str = "31.2304", level: str = "住宅区") -> str:
    return json.dumps(
        {
            "status": "1",
            "info": "OK",
            "count": "1",
            "geocodes": [
                {
                    "formatted_address": "上海市黄浦区人民广场",
                    "location": f"{lon},{lat}",
                    "level": level,
                }
            ],
        }
    )


def test_amap_response_is_parsed_and_converted_to_wgs84() -> None:
    from tools.geocode_client import parse_amap_response

    result = parse_amap_response(_amap_ok_body())

    assert result is not None
    assert result["provider"] == "amap"
    assert result["source_crs"] == "GCJ-02"
    # 存的必须是转换后的 WGS-84，不是原始 GCJ-02
    assert result["latitude"] != 31.2304
    assert result["longitude"] < 121.4737  # 经度必然西移
    # 原始值保留，便于回查和与服务商侧对账
    assert result["raw_latitude"] == 31.2304
    assert result["raw_longitude"] == 121.4737
    assert result["level"] == "住宅区"


def test_amap_zero_result_returns_none() -> None:
    from tools.geocode_client import parse_amap_response

    body = json.dumps({"status": "1", "info": "OK", "count": "0", "geocodes": []})

    assert parse_amap_response(body) is None


def test_amap_error_status_raises_with_info() -> None:
    from tools.geocode_client import GeocodeProviderError, parse_amap_response

    body = json.dumps({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"})

    try:
        parse_amap_response(body)
    except GeocodeProviderError as error:
        assert "INVALID_USER_KEY" in str(error)
    else:
        raise AssertionError("无效 key 必须抛错，不能当成“查不到”静默跳过")


def test_amap_quota_exhausted_raises_distinct_error() -> None:
    """额度耗尽要能和“查不到”区分，否则会把整批目标标记成无坐标。"""
    from tools.geocode_client import GeocodeQuotaExceeded, parse_amap_response

    body = json.dumps({"status": "0", "info": "DAILY_QUERY_OVER_LIMIT", "infocode": "10003"})

    try:
        parse_amap_response(body)
    except GeocodeQuotaExceeded:
        pass
    else:
        raise AssertionError("额度耗尽必须抛 GeocodeQuotaExceeded")


def test_amap_malformed_location_returns_none() -> None:
    from tools.geocode_client import parse_amap_response

    body = json.dumps(
        {
            "status": "1",
            "info": "OK",
            "count": "1",
            "geocodes": [{"location": "not-a-coordinate", "level": "住宅区"}],
        }
    )

    assert parse_amap_response(body) is None


# ---------- 结果可信度过滤 ----------


def test_low_precision_levels_are_rejected() -> None:
    """“市”级结果等于没有小区信息，存进去会污染同小区比价。"""
    from tools.geocode_client import is_acceptable_level

    assert is_acceptable_level("住宅区") is True
    assert is_acceptable_level("兴趣点") is True
    assert is_acceptable_level("道路") is True
    assert is_acceptable_level("市") is False
    assert is_acceptable_level("省") is False
    assert is_acceptable_level("") is False


def test_result_outside_china_bounds_is_rejected() -> None:
    from tools.geocode_client import is_plausible_china_coordinate

    assert is_plausible_china_coordinate(31.23, 121.47) is True
    assert is_plausible_china_coordinate(0.0, 0.0) is False
    assert is_plausible_china_coordinate(51.5, -0.12) is False  # 伦敦
    assert is_plausible_china_coordinate(None, None) is False


# ---------- 客户端行为（mock HTTP）----------


def test_client_builds_amap_request_with_key_and_query() -> None:
    from tools.geocode_client import AmapGeocoder

    calls: list[str] = []

    def _fake_fetch(url: str, *, timeout: float) -> str:
        calls.append(url)
        return _amap_ok_body()

    client = AmapGeocoder(api_key="TESTKEY", fetch=_fake_fetch)
    result = client.geocode("上海市黄浦区人民广场")

    assert result is not None
    assert len(calls) == 1
    request = urlsplit(calls[0])
    assert request.scheme == "https"
    assert request.hostname == "restapi.amap.com"
    assert request.path == "/v3/geocode/geo"
    assert parse_qs(request.query)["key"] == ["TESTKEY"]
    assert parse_qs(request.query)["address"] == ["上海市黄浦区人民广场"]


def test_client_caches_repeated_queries_to_save_quota() -> None:
    from tools.geocode_client import AmapGeocoder

    calls: list[str] = []

    def _fake_fetch(url: str, *, timeout: float) -> str:
        calls.append(url)
        return _amap_ok_body()

    client = AmapGeocoder(api_key="K", fetch=_fake_fetch)
    client.geocode("同一个地址")
    client.geocode("同一个地址")

    assert len(calls) == 1, "重复查询必须走缓存，额度很宝贵"


def test_client_caches_negative_results_too() -> None:
    from tools.geocode_client import AmapGeocoder

    calls: list[str] = []

    def _fake_fetch(url: str, *, timeout: float) -> str:
        calls.append(url)
        return json.dumps({"status": "1", "info": "OK", "count": "0", "geocodes": []})

    client = AmapGeocoder(api_key="K", fetch=_fake_fetch)
    assert client.geocode("查不到的地址") is None
    assert client.geocode("查不到的地址") is None

    assert len(calls) == 1, "查不到的结果也要缓存，否则重跑会重复烧额度"


def test_client_rejects_empty_query_without_spending_quota() -> None:
    from tools.geocode_client import AmapGeocoder

    calls: list[str] = []

    def _fake_fetch(url: str, *, timeout: float) -> str:
        calls.append(url)
        return _amap_ok_body()

    client = AmapGeocoder(api_key="K", fetch=_fake_fetch)

    assert client.geocode("") is None
    assert client.geocode("   ") is None
    assert calls == []


def test_client_counts_calls_for_quota_tracking() -> None:
    from tools.geocode_client import AmapGeocoder

    client = AmapGeocoder(api_key="K", fetch=lambda url, *, timeout: _amap_ok_body())

    client.geocode("地址一")
    client.geocode("地址二")
    client.geocode("地址一")  # 缓存命中，不计数

    assert client.call_count == 2


def test_client_requires_api_key() -> None:
    from tools.geocode_client import AmapGeocoder

    try:
        AmapGeocoder(api_key="", fetch=lambda url, *, timeout: "")
    except ValueError:
        pass
    else:
        raise AssertionError("缺 key 必须立刻报错，不要等到发请求才失败")
