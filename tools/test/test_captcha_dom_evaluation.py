"""Execute the actual CDP expressions against controlled document trees in Node."""

import json
import shutil
import subprocess

from src.captcha_dom import SLIDER_SELECTORS, TRACK_SELECTORS
from src.captcha_nc_retry import CaptchaNCRetryMixin
from src.captcha_preflight import CaptchaPreflightMixin
from src.captcha_slider import CaptchaSliderMixin

NODE_FIXTURE = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(spec) {
    return {...spec, offsetParent: spec.hidden || spec.fixed ? null : {},
        ownerDocument: {defaultView: {getComputedStyle: () => ({display: spec.hidden ? 'none' : 'block', visibility: 'visible', opacity: '1', position: spec.fixed ? 'fixed' : 'static'})}},
        getBoundingClientRect: () => ({left: 5, top: 8, width: 100, height: 20, ...spec.rect})};
}
function doc(spec) {
    const nodes = (spec.nodes || []).map(element);
    const frames = (spec.frames || []).map(frame => {
        const node = element(frame);
        Object.defineProperty(node, 'contentDocument', {get() {
            if (frame.crossOrigin) throw Error('cross-origin');
            return frame.document ? doc(frame.document) : null;
        }});
        return node;
    });
    const matches = (node, query) => query.split(',').some(s => (node.selectors || []).includes(s.trim()));
    return {
        body: {innerText: spec.text || '', className: spec.className || ''},
        title: spec.title || '', location: {href: spec.url || ''}, readyState: spec.readyState || 'complete',
        documentElement: {outerHTML: spec.html || ''},
        querySelector: query => nodes.find(node => matches(node, query)) || null,
        querySelectorAll: query => query === 'div, span, p, button, a' ? nodes : nodes.filter(node => matches(node, query)),
        getElementsByTagName: tag => tag === 'iframe' ? frames : [],
        getElementById: id => nodes.find(node => matches(node, '#' + id)) || null,
    };
}
const value = vm.runInNewContext(input.expression, {document: doc(input.document), window: {}, URL}, {timeout: 1000});
process.stdout.write(JSON.stringify(value));
"""


class DocumentSolver(CaptchaSliderMixin, CaptchaPreflightMixin, CaptchaNCRetryMixin):
    SLIDER_SELECTORS = SLIDER_SELECTORS
    TRACK_SELECTORS = TRACK_SELECTORS

    def __init__(self, document, target_url=None):
        self.document = document
        self.target_url = target_url

    def _local_mock_verification_mode(self):
        return ""

    def _send_cdp(self, method, params):
        assert method == "Runtime.evaluate"
        node = shutil.which("node")
        assert node, "Node is required for CDP expression tests"
        result = subprocess.run(
            [node, "-e", NODE_FIXTURE],
            input=json.dumps(
                {
                    "expression": params["expression"],
                    "document": self.document,
                }
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=5,
            check=True,
        )
        return {"result": {"value": json.loads(result.stdout)}}


def slider(**extra):
    return {"selectors": ["#nc_1_n1z"], **extra}


def test_main_match_precedes_iframe_and_keeps_selector_priority():
    solver = DocumentSolver(
        {"nodes": [slider()], "frames": [{"document": {"nodes": [slider()]}}]}
    )
    result = solver._find_slider_once()
    assert (result["context"], result["selector"], result["x"], result["y"]) == (
        "main",
        "#nc_1_n1z",
        5,
        8,
    )


def test_cross_origin_is_skipped_and_zero_x_iframe_is_not_labeled_main():
    solver = DocumentSolver(
        {
            "frames": [
                {"crossOrigin": True},
                {"rect": {"left": 0, "top": 40}, "document": {"nodes": [slider()]}},
            ]
        }
    )
    result = solver._find_slider_once()
    assert (result["context"], result["x"], result["y"]) == ("iframe", 5, 48)


def test_nested_iframes_do_not_silently_expand_the_scan_scope():
    solver = DocumentSolver(
        {"frames": [{"document": {"frames": [{"document": {"nodes": [slider()]}}]}}]}
    )
    assert solver._find_slider_once() is None


def test_track_in_iframe_retains_local_rectangle_and_handle_offsets():
    solver = DocumentSolver(
        {
            "frames": [
                {
                    "rect": {"left": 300},
                    "document": {
                        "nodes": [
                            {
                                "selectors": [".nc_scale"],
                                "rect": {"left": 20, "width": 310},
                                "offsetWidth": 310,
                            },
                            slider(offsetLeft=3, offsetWidth=30),
                        ]
                    },
                }
            ]
        }
    )
    assert solver._get_track_width() == 310
    rect = solver._get_track_rect()
    assert rect["left"] == 20
    assert (rect["handleOffsetLeft"], rect["handleOffsetWidth"]) == (3, 30)


def test_hidden_frame_does_not_override_valid_auction_payload():
    solver = DocumentSolver(
        {
            "url": "https://sf-item.taobao.com/sf_item/123.htm",
            "text": "auction evidence " * 12,
            "html": '<html><body><div id="J_StartPrice">123</div></body></html>',
            "frames": [
                {"hidden": True, "document": {"nodes": [slider()], "text": "验证失败"}}
            ],
        },
        target_url="https://sf-item.taobao.com/sf_item/123.htm",
    )
    summary = solver._page_challenge_summary()
    assert summary["authenticatedPage"] is True
    assert summary["challengePresent"] is False


def test_visible_frame_challenge_blocks_successful_main_payload():
    solver = DocumentSolver(
        {
            "url": "https://sf-item.taobao.com/sf_item/123.htm",
            "text": "auction evidence " * 12,
            "html": '<html><body><div id="J_StartPrice">123</div></body></html>',
            "frames": [{"document": {"nodes": [slider()]}}],
        },
        target_url="https://sf-item.taobao.com/sf_item/123.htm",
    )
    summary = solver._page_challenge_summary()
    assert summary["hasSlider"] and summary["challengePresent"]
    assert not summary["authenticatedPage"]


def test_retry_targets_merge_visible_frames_and_apply_offsets():
    solver = DocumentSolver(
        {
            "nodes": [{"selectors": [".nc_scale"]}],
            "frames": [
                {"hidden": True, "document": {"nodes": [slider()]}},
                {
                    "rect": {"left": 50, "top": 70},
                    "document": {"nodes": [slider(), {"selectors": [".errloading"]}]},
                },
            ],
        }
    )
    summary = solver._nc_retry_targets()
    assert summary["widget"]["x"] == 5
    assert (summary["slider"]["x"], summary["slider"]["y"]) == (55, 78)
    assert summary["retryText"]["x"] == 55


def test_widget_rect_remains_main_only_but_verification_rejects_visible_frame():
    solver = DocumentSolver(
        {
            "text": "success",
            "url": "https://sf-item.taobao.com/sf_item/123.htm",
            "frames": [
                {"document": {"nodes": [slider(), {"selectors": [".nc_scale"]}]}}
            ],
        },
        target_url="https://sf-item.taobao.com/sf_item/123.htm",
    )
    assert solver._nc_widget_rect() is None
    assert solver._verify_success() is False
