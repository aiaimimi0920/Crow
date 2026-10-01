from __future__ import annotations

from pathlib import Path

from tools import js_surface


def test_repo_js_syntax_check_files_inventory_matches_current_surface():
    repo_root = Path(__file__).resolve().parents[2]

    assert [path.relative_to(repo_root) for path in js_surface.repo_js_syntax_check_files(repo_root)] == [
        Path("game/web-app/src/composables/useGameState.js"),
        Path("game/web-app/src/main.js"),
        Path("game/web-app/tailwind.config.js"),
        Path("game/web-app/vite.config.js"),
        Path("tampermonkey_scripts/fapaifang_unified.user.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/00_bootstrap.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/100_detail_helper_actions.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/10_sniff_collection.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/110_dispatch_and_captcha.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/20_sniff_challenge.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/30_sniff_dashboard.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/40_fast_review_loop.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/50_fast_review_item.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/60_slow_review.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/70_detail_worker.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/80_detail_helper_context.js"),
        Path("tampermonkey_scripts/src/fapaifang_unified/90_detail_helper_panel.js"),
        Path("userscripts/nc_captcha_solver.user.js"),
    ]


def test_repo_js_syntax_check_files_ignore_operator_output_tree(tmp_path: Path):
    tracked_script = tmp_path / "tampermonkey_scripts" / "fapaifang_unified.user.js"
    tracked_script.parent.mkdir(parents=True)
    tracked_script.write_text("const tracked = true;\n", encoding="utf-8")
    generated_script = tmp_path / "output" / "taobao-auth-profile" / "extension.js"
    generated_script.parent.mkdir(parents=True)
    generated_script.write_text("this file is generated operator output\n", encoding="utf-8")

    assert js_surface.repo_js_syntax_check_files(tmp_path) == [tracked_script]


def test_repo_js_syntax_check_files_include_and_reject_invalid_source_units(tmp_path: Path):
    built_script = tmp_path / "tampermonkey_scripts" / "fapaifang_unified.user.js"
    built_script.parent.mkdir(parents=True)
    built_script.write_text("const built = true;\n", encoding="utf-8")
    fragment = (
        tmp_path
        / "tampermonkey_scripts"
        / "src"
        / "fapaifang_unified"
        / "00_bootstrap.js"
    )
    fragment.parent.mkdir(parents=True)
    fragment.write_text("(() => {\n", encoding="utf-8")
    independent_source = tmp_path / "tampermonkey_scripts" / "src" / "independent.js"
    independent_source.write_text("const independent = true;\n", encoding="utf-8")

    assert js_surface.repo_js_syntax_check_files(tmp_path) == [
        built_script,
        fragment,
        independent_source,
    ]
    failures = js_surface.node_check_repo_js_surface(tmp_path)
    assert len(failures) == 1
    assert failures[0][0] == fragment
    assert failures[0][1] != 0


def test_repo_js_syntax_check_files_pass_node_check():
    repo_root = Path(__file__).resolve().parents[2]

    failures = js_surface.node_check_repo_js_surface(repo_root)

    assert failures == []
