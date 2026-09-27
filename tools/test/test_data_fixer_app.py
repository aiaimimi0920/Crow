"""Headless behavior coverage for the legacy data repair application's assembly."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src import data_fixer, data_fixer_runtime


def make_app():
    app = object.__new__(data_fixer.DataFixerApp)
    app.log = Mock()
    return app


def test_save_alias_updates_only_the_matching_record(tmp_path):
    path = tmp_path / "records.json"
    original = [
        {"id": "1", "建筑面积": 80, "起拍价格": 800000, "_evidence": "retained"},
        {"id": "2", "建筑面积": 90, "_evidence": "untouched"},
    ]
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    app = make_app()

    assert app.save_area({"id": "1", "json_file": str(path), "建筑面积": 100})

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[0] == {**original[0], "建筑面积": 100.0, "单价": 8000.0}
    assert saved[1] == original[1]
    before = path.read_bytes()
    assert not app.save_record({"id": "absent", "json_file": str(path)})
    assert path.read_bytes() == before


def test_batch_approval_preserves_selection_and_save_failure_behavior():
    app = make_app()
    first, second = {"id": "1"}, {"id": "2"}
    app.row_widgets = [
        {
            "idx": 1,
            "item": first,
            "checkbox": Mock(get=lambda: True),
            "area_var": Mock(get=lambda: "80.5"),
        },
        {
            "idx": 2,
            "item": second,
            "checkbox": Mock(get=lambda: True),
            "area_var": Mock(get=lambda: "90"),
        },
        {"idx": 3, "checkbox": Mock(get=lambda: False)},
    ]
    app.save_area = Mock(side_effect=[True, False])
    app.remove_row = Mock()
    app.select_all_btn = Mock()
    app.all_selected = True

    app.batch_approve()

    assert first["建筑面积"] == 80.5
    assert second["建筑面积"] == 90
    assert app.save_area.call_count == 2
    app.remove_row.assert_called_once_with(1)
    assert app.all_selected is False
    app.select_all_btn.config.assert_called_once_with(text="☐ 全选")


def test_selection_pause_and_ai_stats_use_the_current_controls():
    app = make_app()
    selection = Mock()
    app.row_widgets = [{"checkbox": selection, "idx": 4}]
    app.all_selected = False
    app.select_all_btn = Mock()
    app.toggle_select_all()
    selection.set.assert_called_once_with(True)
    selection.get.return_value = True
    app.remove_row = Mock()
    app.skip_selected()
    app.remove_row.assert_called_once_with(4)
    assert app.all_selected is False

    app.start_btn, app.pause_btn, app.scraping_status = Mock(), Mock(), Mock()
    app.is_scraping = True
    app.pause_scraping()
    assert app.is_scraping is False
    app.start_btn.config.assert_called_once_with(state="normal")
    app.pause_btn.config.assert_called_once_with(state="disabled")

    app.ai_stats_label = Mock()
    app.ai_approved_count, app.ai_rejected_count = 5, 2
    app._update_ai_stats()
    app.ai_stats_label.config.assert_called_once_with(text="AI通过: 5 | 待定: 2")


def test_log_writes_to_the_widget_and_tolerates_a_closed_window():
    app = object.__new__(data_fixer.DataFixerApp)
    app.log_text = Mock()
    app.log("repair complete")
    assert app.log_text.insert.call_args.args[1].endswith(" repair complete\n")
    app.log_text.see.assert_called_once_with("end")
    app.log_text.config.side_effect = RuntimeError("window closed")
    app.log("after close")


def test_open_alias_keeps_browser_url_validation(monkeypatch):
    import webbrowser

    opened = Mock()
    monkeypatch.setattr(webbrowser, "open", opened)
    app = make_app()
    app.open_url({"url": "javascript:alert(1)"})
    opened.assert_not_called()
    app.open_url({"url": "https://example.test/item"}, auto=True)
    opened.assert_called_once_with(
        "https://example.test/item?uni_port=5001&auto_fix=1", new=0, autoraise=False
    )


def test_main_constructs_the_application_before_entering_event_loop(monkeypatch):
    calls = []
    root = SimpleNamespace(mainloop=lambda: calls.append("mainloop"))
    monkeypatch.setattr(data_fixer_runtime.tk, "Tk", lambda: root)
    monkeypatch.setattr(data_fixer, "DataFixerApp", lambda window: calls.append(window))

    data_fixer.main()

    assert calls == [root, "mainloop"]


def test_package_import_keeps_location_normalization_without_optional_ai(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r}); "
                "sys.modules['src.llm_helper'] = None; "
                "from src import data_fixer, data_fixer_context; "
                "from src import data_fixer_app_part_03 as ai; "
                "from src.data_fixer_app_part_05 import DataFixerAppPart05; "
                "assert data_fixer_context.AI_AVAILABLE is False; "
                "assert ai.get_model_pool() == []; "
                "assert ai.simple_ai_call('unused') == ''; "
                "assert callable(data_fixer_context.resolve_community_name); "
                "assert data_fixer.DataFixerApp.save_record is DataFixerAppPart05.save_record; "
                "assert 'src.server_context' not in sys.modules; "
                "assert 'src.server' not in sys.modules"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
