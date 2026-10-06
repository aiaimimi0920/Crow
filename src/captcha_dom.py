"""Selector policy and same-origin, one-level iframe evaluation helpers."""

import json

FALLBACK_SLIDER = "#nc_1_n1z, .btn_slide"
FALLBACK_STEALTH_SLIDER = "#nc_1_n1z, .btn_slide, .nc-slider-btn"
FALLBACK_TRACK = "#nc_1_n1t, .nc_scale"
OCR_TRACK = "#nc_1_n1t"
OCR_BACKGROUND = ".nc_bg, canvas"
OCR_PIECE = ".nc_slider"
WIDGET_SCREENSHOT = ".nc_wrapper"

SLIDER_SELECTORS = (
    "#nc_1_n1z",
    "#nc_2_n1z",
    '[id^="nc_"][id$="_n1z"]',
    "#nc_1_n1t",
    "#nc_2_n1t",
    '[id^="nc_"][id$="_n1t"]',
    ".btn_slide",
    ".nc_iconfont.btn_slide",
    ".nc_scale .btn_slide",
    ".nc_wrapper .btn_slide",
    ".nc-slider-btn",
    ".slider-btn",
    ".nc-lang-cnt .btn_ok",
    ".btn_ok",
    ".icon-slide-arrow",
    ".nc-iconfont.icon-slide-arrow",
    "#mock-slider-handle",
)
TRACK_SELECTORS = (
    "#nc_1_n1t",
    "#nc_2_n1t",
    '[id^="nc_"][id$="_n1t"]',
    ".nc_scale",
    ".nc-lang-cnt",
    ".scale_text",
    ".slidetounlock",
    ".nc_wrapper",
    ".nc_scale_text",
    '[id^="nc_"][id*="scale_text"]',
    ".slider",
    ".nc-container .slider",
    "#mock-slider-track",
)
SELECTOR_GROUPS = {
    "NC_HANDLE": '#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], .btn_slide, .nc-slider-btn',
    "NC_WIDGET": ".nc_scale, #nc_1_n1t, #nc_2_n1t, .nc-container, .nc_wrapper",
    "NC_ERROR": '.errloading, [id*="_refresh1"], [id*="refresh1"]',
    "PREFLIGHT_SLIDER": '#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], #nc_1_n1t, #nc_2_n1t, [id^="nc_"][id$="_n1t"], .btn_slide, .nc_iconfont.btn_slide, .nc-slider-btn, .slider-btn',
    "VERIFY_SLIDER": '#nc_1_n1z, #nc_2_n1z, [id^="nc_"][id$="_n1z"], #nc_1_n1t, #nc_2_n1t, [id^="nc_"][id$="_n1t"], .btn_slide, .nc-slider-btn, .slider-btn, .icon-slide-arrow',
    "VERIFY_CHALLENGE": ".nc-container, #nocaptcha, .nc_wrapper, .nc_scale",
}

_FRAME_VISITOR = """
function verificationElementVisible(node) {
    if (!node) return false;
    var view = node.ownerDocument && node.ownerDocument.defaultView;
    var style = view && view.getComputedStyle ? view.getComputedStyle(node) : null;
    if (style && (style.display === 'none' || style.visibility === 'hidden' ||
        style.visibility === 'collapse' || parseFloat(style.opacity) === 0)) return false;
    var rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 &&
        (node.offsetParent !== null || !!(style && style.position === 'fixed'));
}
function hasVisibleMatch(doc, selector) {
    var nodes = doc.querySelectorAll(selector);
    for (var n = 0; n < nodes.length; n++) {
        if (verificationElementVisible(nodes[n])) return true;
    }
    return false;
}
function visitAccessibleDocuments(visitor, visibleOnly) {
    var result = visitor(document, 0, 0, 'main');
    if (result) return result;
    var frames = document.getElementsByTagName('iframe');
    for (var i = 0; i < frames.length; i++) {
        try {
            var frame = frames[i];
            if (visibleOnly && !verificationElementVisible(frame)) continue;
            var doc = frame.contentDocument;
            if (!doc) continue;
            var rect = frame.getBoundingClientRect();
            result = visitor(doc, rect.left, rect.top, 'iframe');
            if (result) return result;
        } catch (error) {}
    }
    return null;
}
"""


def eval_in_all_frames(expression: str) -> str:
    """Bind selectors and expose a visitor; the caller chooses first-match or merge."""
    for name, selector in SELECTOR_GROUPS.items():
        expression = expression.replace(f"__{name}_SELECTOR__", json.dumps(selector))
    return "(function() {\n" + _FRAME_VISITOR + "\nreturn (" + expression + ");\n})()"
