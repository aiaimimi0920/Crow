import pytest

from src.analysis.six_month.city_reference import parse_snapshot, visible_asof

URL = "https://www.stats.gov.cn/sj/zxfb/202302/old.html"
RETRIEVED = "2026-11-18T00:00:00+00:00"


def page(meta=True):
    published = (
        '<meta name="PubDate" content="2020/07/16 09:30">'
        if meta
        else "<p>2020/07/16 09:30</p>"
    )
    rows = "".join(
        f"<tr><td>{city}</td><td>99.5</td><td>90.1</td><td>123.4</td>"
        "<td>上海</td><td>88.8</td><td>99.9</td><td>111.1</td></tr>"
        for city in ("北 京", "武汉", "温州", "宜昌")
    )
    return (
        published + "<p>表2：2020年6月70个大中城市二手住宅销售价格指数</p>"
        "<table><tr>"
        + "<td>城市</td><td>环比</td><td>同比</td><td>定基</td>" * 2
        + "</tr><tr>"
        + "<td>上月=100</td><td>上年同月=100</td><td>2015年=100</td>" * 2
        + "</tr>"
        + rows
        + "</table>"
    ).encode()


@pytest.mark.parametrize("meta", [True, False])
def test_old_url_and_training_only(meta):
    report = parse_snapshot(page(meta), URL, RETRIEVED)
    assert report["published_at"] == "2020-07-16T09:30:00+08:00"
    assert report["city_indices"] == dict.fromkeys(
        ["北京", "武汉", "温州", "宜昌"], 99.5
    )
    assert report["community_price_labels"] == report["market_predictions"] == []
    assert not report["historical_vintage_verified"]
    assert not visible_asof(report, "2025-01-01T00:00:00+08:00")
    assert visible_asof(report, RETRIEVED)
    with pytest.raises(ValueError):
        visible_asof(report, "2026-11-18")


@pytest.mark.parametrize(
    "old,new",
    [
        ("表2", "表1"),
        ("二手住宅", "新建商品住宅"),
        ("上月=100", "上年同月=100"),
        ("宜昌", "不存在"),
        ("99.5", "NaN"),
        ("99.5", "0"),
    ],
)
def test_reject_bad_tables(old, new):
    with pytest.raises(ValueError):
        parse_snapshot(page().decode().replace(old, new).encode(), URL, RETRIEVED)


def test_time_and_source_guards():
    with pytest.raises(ValueError):
        parse_snapshot(page(), URL, "2020-07-15T00:00:00+00:00")
    with pytest.raises(ValueError):
        parse_snapshot(page(), URL, "2026-11-18")
    with pytest.raises(ValueError):
        parse_snapshot(page(), "https://other.test/page", RETRIEVED)
    with pytest.raises(ValueError):
        parse_snapshot(page().replace(b"2020/07/16", b"2020/06/16"), URL, RETRIEVED)


@pytest.mark.parametrize("month", ["0", "13"])
def test_invalid_calendar_month(month):
    raw = page().decode().replace("2020年6月", f"2019年{month}月").encode()
    with pytest.raises(ValueError):
        parse_snapshot(raw, URL, RETRIEVED)


def test_reordered_index_columns_fail_closed():
    text = (
        page()
        .decode()
        .replace("<td>环比</td><td>同比</td>", "<td>同比</td><td>环比</td>")
    )
    text = text.replace(
        "<td>上月=100</td><td>上年同月=100</td>",
        "<td>上年同月=100</td><td>上月=100</td>",
    )
    with pytest.raises(ValueError):
        parse_snapshot(text.encode(), URL, RETRIEVED)


def test_reordered_base_row_alone_fails():
    text = (
        page()
        .decode()
        .replace(
            "<td>上月=100</td><td>上年同月=100</td>",
            "<td>上年同月=100</td><td>上月=100</td>",
        )
    )
    with pytest.raises(ValueError):
        parse_snapshot(text.encode(), URL, RETRIEVED)
