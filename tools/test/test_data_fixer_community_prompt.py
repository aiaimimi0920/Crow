from __future__ import annotations

import json
from pathlib import Path

from src import data_fixer
from src import data_fixer_app_part_03 as data_fixer_ai

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _new_app_without_tk() -> data_fixer.DataFixerApp:
    app = data_fixer.DataFixerApp.__new__(data_fixer.DataFixerApp)
    app.log = lambda *_args, **_kwargs: None
    return app


def test_data_fixer_source_prompts_use_stable_location_index_contract():
    source_paths = [
        SRC_ROOT / "data_fixer.py",
        *sorted(SRC_ROOT.glob("data_fixer_*.py")),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    assert "参考贝壳网数据库" not in source
    assert "标准小区名称" not in source
    assert "使用标准小区名称" not in source
    assert source.count("稳定位置索引名") >= 4
    assert "不要求官方名称" in source
    assert "不要输出城市、区县、道路门牌号、楼号、单元号、房号" in source


def test_infer_location_ai_prompt_uses_stable_location_index_contract(monkeypatch):
    captured: list[str] = []

    def fake_simple_ai_call(prompt: str, pool_idx=None):
        captured.append(prompt)
        return '{"所属小区": "朝阳区八里庄位置片区", "最靠近商圈": "八里庄"}'

    monkeypatch.setattr(data_fixer_ai, "AI_AVAILABLE", True)
    monkeypatch.setattr(data_fixer_ai, "get_model_pool", lambda: [{"name": "fake"}])
    monkeypatch.setattr(data_fixer_ai, "simple_ai_call", fake_simple_ai_call)

    result = _new_app_without_tk()._infer_location_ai(
        "北京市朝阳区八里庄远洋天地小区7号楼1单元101室",
        title="远洋天地住宅拍卖",
    )

    assert result == {"所属小区": "朝阳区八里庄位置片区", "最靠近商圈": "八里庄"}
    prompt = captured[0]
    assert "稳定位置索引名" in prompt
    assert "不要求官方名称" in prompt
    assert "不要输出城市、区县、道路门牌号、楼号、单元号、房号" in prompt


def test_infer_full_info_ai_prompt_uses_stable_location_index_contract(monkeypatch):
    captured: list[str] = []

    def fake_simple_ai_call(prompt: str, pool_idx=None):
        captured.append(prompt)
        return '{"所属小区": "朝阳区八里庄位置片区", "最靠近商圈": "八里庄", "建筑面积": 88.5}'

    monkeypatch.setattr(data_fixer_ai, "AI_AVAILABLE", True)
    monkeypatch.setattr(
        data_fixer_ai,
        "get_model_pool",
        lambda: [{"name": "fake"}, {"name": "fake-infer"}],
    )
    monkeypatch.setattr(data_fixer_ai, "simple_ai_call", fake_simple_ai_call)

    result = _new_app_without_tk()._infer_full_info_ai(
        {
            "地点": "北京市朝阳区八里庄远洋天地小区7号楼1单元101室",
            "title": "远洋天地住宅拍卖",
            "context": "标的物位于远洋天地小区，建筑面积88.5平方米。",
        }
    )

    assert result["所属小区"] == "朝阳区八里庄位置片区"
    assert result["最靠近商圈"] == "八里庄"
    assert result["建筑面积"] == 88.5
    prompt = captured[0]
    assert "稳定位置索引名" in prompt
    assert "同一小区或同一片房源应尽量输出同一个名字" in prompt
    assert "不要输出城市、区县、道路门牌号、楼号、单元号、房号" in prompt


def test_save_record_normalizes_address_like_community_name_before_writing(
    tmp_path: Path,
):
    full_address = "北京市朝阳区八里庄远洋天地小区7号楼1单元101室"
    data_file = tmp_path / "records.json"
    data_file.write_text('[{"id": "1001", "title": "待修复法拍房"}]', encoding="utf-8")

    result = _new_app_without_tk().save_record(
        {"id": "1001", "json_file": str(data_file)},
        new_data={
            "所属小区": full_address,
            "地点": full_address,
            "城市": "北京市",
            "区": "朝阳区",
            "最靠近商圈": "八里庄",
            "建筑面积": 80,
            "成交价格": 800000,
        },
    )

    assert result is True
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    saved = payload[0]
    assert saved["所属小区"] == "朝阳区八里庄位置片区"
    assert saved["community_name"] == "朝阳区八里庄位置片区"
    assert saved["community_name_source"] == "geo_fallback"
    assert saved["community_raw_name"] == full_address
    assert saved["community_stable_key"] == "geo::北京市::朝阳区::八里庄"


def test_save_record_uses_district_anchor_when_business_area_is_missing(tmp_path: Path):
    full_address = "北京市朝阳区远洋天地小区7号楼1单元101室"
    data_file = tmp_path / "records.json"
    data_file.write_text('[{"id": "1002", "title": "待修复法拍房"}]', encoding="utf-8")

    result = _new_app_without_tk().save_record(
        {"id": "1002", "json_file": str(data_file)},
        new_data={
            "所属小区": full_address,
            "地点": full_address,
            "城市": "北京市",
            "区": "朝阳区",
            "建筑面积": 80,
            "成交价格": 800000,
        },
    )

    assert result is True
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    saved = payload[0]
    assert saved["所属小区"] == "朝阳区位置片区"
    assert saved["community_name_source"] == "geo_fallback"
    assert saved["community_name_confidence"] == 0.35
    assert saved["community_stable_key"] == "geo::北京市::朝阳区"
