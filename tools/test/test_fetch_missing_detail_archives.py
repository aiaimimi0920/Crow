import json
from pathlib import Path

from src.collection import detail_archive_fetch as fetch_module
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools.fetch_missing_detail_archives import fetch_missing_detail_archives


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "fetch-detail.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeSession:
    def __init__(self, html: str, expected_url: str = "https://example.com/item/3001"):
        self.html = html
        self.headers = {}
        self.expected_url = expected_url

    def get(self, url: str, timeout: int):
        assert url == self.expected_url
        assert timeout == 5
        return _FakeResponse(self.html)


def test_fetch_missing_detail_archives_fetches_html_and_syncs_json_and_db(
    tmp_path: Path, monkeypatch
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_file = archive_dir / "2026-03-05.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 3001,
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "原始网站": "https://example.com/item/3001",
                    "detail_captured": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": 3001,
            "交易时间": "2026-03-05 10:00:00",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "城市": "上海市",
            "区": "浦东新区",
            "原始网站": "https://example.com/item/3001",
            "detail_captured": True,
        },
        event_type="seed",
        event_payload={"source_file": str(data_file)},
    )

    monkeypatch.setattr(fetch_module, "create_repository_from_env", lambda: repo)
    monkeypatch.setattr(
        fetch_module.requests,
        "Session",
        lambda: _FakeSession(
            "<html><body>"
            "<script>var center=[121.5001,31.2002];</script>"
            '<div id="J_NoticeDetail">测试公告正文</div>'
            '<a href="https://example.com/report.pdf">评估报告</a>'
            '<img src="https://example.com/pic.jpg" />'
            "</body></html>"
        ),
    )

    report = fetch_missing_detail_archives(
        data_root=data_root, limit=10, timeout=5, dry_run=False
    )

    assert report["fetched_count"] == 1
    html_file = data_root / "html_archive" / "2026" / "2026-03-05" / "item-3001.html"
    assert html_file.exists()

    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert (
        payload[0]["detail_archive_path"]
        == "html_archive/2026/2026-03-05/item-3001.html"
    )
    assert payload[0]["latitude"] == 31.2002
    assert payload[0]["longitude"] == 121.5001
    assert (
        payload[0]["notice_text_path"]
        == "html_archive/2026/2026-03-05/item-3001.notice.txt"
    )
    assert (
        payload[0]["attachment_manifest_path"]
        == "html_archive/2026/2026-03-05/item-3001.attachments.json"
    )
    assert (
        payload[0]["image_manifest_path"]
        == "html_archive/2026/2026-03-05/item-3001.images.json"
    )

    assert (data_root / payload[0]["notice_text_path"]).exists()
    assert (data_root / payload[0]["attachment_manifest_path"]).exists()
    assert (data_root / payload[0]["image_manifest_path"]).exists()

    db_item = repo.get_flat_item("3001")
    assert db_item is not None
    assert (
        db_item["detail_archive_path"] == "html_archive/2026/2026-03-05/item-3001.html"
    )
    assert db_item["latitude"] == 31.2002
    assert db_item["longitude"] == 121.5001
    assert (
        db_item["notice_text_path"]
        == "html_archive/2026/2026-03-05/item-3001.notice.txt"
    )
    assert db_item["detail_fetch_status"] == "success"


def test_fetch_missing_detail_archives_marks_login_gate_as_blocked(
    tmp_path: Path, monkeypatch
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_file = archive_dir / "2026-03-05.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 3002,
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "原始网站": "https://example.com/item/3002",
                    "detail_captured": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": 3002,
            "交易时间": "2026-03-05 10:00:00",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "城市": "上海市",
            "区": "浦东新区",
            "原始网站": "https://example.com/item/3002",
            "detail_captured": True,
        },
        event_type="seed",
        event_payload={"source_file": str(data_file)},
    )

    monkeypatch.setattr(fetch_module, "create_repository_from_env", lambda: repo)
    monkeypatch.setattr(
        fetch_module.requests,
        "Session",
        lambda: _FakeSession(
            '<a id="a-link"></a><script>var host="https://login.taobao.com/member/login.jhtml?redirectURL=";'
            'var jump="_____tmd_____"; localStorage.x5referer=window.location.href;</script>',
            expected_url="https://example.com/item/3002",
        ),
    )

    report = fetch_missing_detail_archives(
        data_root=data_root, limit=10, timeout=5, dry_run=False
    )

    assert report["fetched_count"] == 0
    assert report["blocked_count"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload[0]["detail_fetch_status"] in {"login_redirect", "anti_bot_gate"}
    assert "detail_fetch_attempted_at" in payload[0]
    html_file = data_root / "html_archive" / "2026" / "2026-03-05" / "item-3002.html"
    assert not html_file.exists()
    db_item = repo.get_flat_item("3002")
    assert db_item is not None
    assert db_item["detail_fetch_status"] in {"login_redirect", "anti_bot_gate"}


def test_fetch_missing_detail_archives_can_extract_risk_features(
    tmp_path: Path, monkeypatch
):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_file = archive_dir / "2026-03-05.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 3003,
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "原始网站": "https://example.com/item/3003",
                    "detail_captured": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": 3003,
            "交易时间": "2026-03-05 10:00:00",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "城市": "上海市",
            "区": "浦东新区",
            "原始网站": "https://example.com/item/3003",
            "detail_captured": True,
        },
        event_type="seed",
        event_payload={"source_file": str(data_file)},
    )

    monkeypatch.setattr(fetch_module, "create_repository_from_env", lambda: repo)
    monkeypatch.setattr(
        fetch_module.requests,
        "Session",
        lambda: _FakeSession(
            "<html><div id='J_NoticeDetail'>测试公告正文"
            + ("补充说明" * 80)
            + "</div></html>",
            expected_url="https://example.com/item/3003",
        ),
    )
    monkeypatch.setattr(
        fetch_module,
        "extract_avm_risk_features",
        lambda text, item_id=None: {
            "community_name": "测试小区",
            "is_occupied": True,
            "clear_delivery": False,
            "housing_type": "住宅",
            "extraction_confidence": 0.9,
            "evidence_span": "测试公告正文",
            "evidence_source": "公告",
            "extraction_version": "avm_risk_v2",
            "has_long_lease": None,
            "tax_burden": None,
            "is_fractional_share": None,
        },
    )

    report = fetch_missing_detail_archives(
        data_root=data_root, limit=10, timeout=5, extract_risk=True, dry_run=False
    )

    assert report["fetched_count"] == 1
    assert report["samples"][0]["has_risk_features"] is True
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload[0]["avm_risk_features"]["community_name"] == "测试小区"
    assert payload[0]["community_name"] == "测试小区"
    assert payload[0]["is_occupied"] is True
    db_item = repo.get_flat_item("3003")
    assert db_item is not None
    assert db_item["community_name"] == "测试小区"
    assert db_item["detail_fetch_status"] == "success"
