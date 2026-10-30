"""Collect a slider and its own track in one document and one CSS coordinate space."""

import json


class SliderEndpointReached(Exception):
    """Live geometry has no remaining travel; verification must decide the result."""


GEOMETRY_HELPERS = r"""
function sliderTracks(doc, selectors) {
    var tracks = [];
    selectors.forEach(function(selector) {
        Array.from(doc.querySelectorAll(selector)).forEach(function(node) {
            var r = node.getBoundingClientRect();
            if (verificationElementVisible(node) && r.width > 50 && r.height > 5 &&
                tracks.indexOf(node) < 0) tracks.push(node);
        });
    });
    return tracks;
}
function selectedSlider(doc, selectors) {
    for (var i = 0; i < selectors.length; i++) {
        var node = firstVisibleMatch(doc, selectors[i], function(candidate) {
            var r = candidate.getBoundingClientRect();
            return r.width > 5 && r.height > 5;
        });
        if (node) return {node:node, selector:selectors[i]};
    }
    return null;
}
function sliderTrack(doc, handle, selectors, handleSelectors) {
    var tracks = sliderTracks(doc, selectors), allTracks = tracks;
    if (tracks.indexOf(handle) >= 0) return handle;
    var id = String(handle.id || '');
    var expected = /^nc_.+_n1z$/.test(id) ? id.replace(/_n1z$/, '_n1t') : null;
    var group = handle.closest('.nc-container, .nc_wrapper');
    function compatible(track) {
        var trackId = String(track.id || '');
        return (!expected || !/^nc_.+_n1t$/.test(trackId) || trackId === expected) &&
            track.closest('.nc-container, .nc_wrapper') === group;
    }
    var exact = expected && tracks.filter(function(track) { return track.id === expected; });
    if (exact && exact.length > 1) return null;
    if (exact && exact.length === 1) return compatible(exact[0]) ? exact[0] : null;
    tracks = tracks.filter(compatible);
    for (var parent = handle.parentElement; parent; parent = parent.parentElement) {
        if (tracks.indexOf(parent) >= 0) return parent;
    }
    if (group) {
        var related = tracks.filter(function(track) {
            return track.closest('.nc-container, .nc_wrapper') === group;
        });
        if (related.length === 1) return related[0];
    }
    // Retain isolated generic sibling controls, never a conflicting NC identity.
    if (tracks.length !== 1 || allTracks.length !== 1) return null;
    var track = tracks[0];
    var handles = [];
    handleSelectors.forEach(function(selector) {
        Array.from(doc.querySelectorAll(selector)).forEach(function(node) {
            var r = node.getBoundingClientRect();
            if (verificationElementVisible(node) && r.width > 5 && r.height > 5 &&
                allTracks.indexOf(node) < 0 && handles.indexOf(node) < 0) handles.push(node);
        });
    });
    return handles.length === 1 && handles[0] === handle ? track : null;
}
function sliderParents(node) {
    var parents = [];
    for (var p = node.parentElement; p; p = p.parentElement) parents.push(p);
    return parents;
}
function sliderSameParents(node, parents) {
    var p = node.parentElement;
    for (var i = 0; i < parents.length; i++) {
        if (p !== parents[i]) return false;
        p = p.parentElement;
    }
    return !p;
}
function sliderBindingValid(anchor) {
    var node = anchor.node, track = anchor.track;
    return Date.now() < anchor.expiresAt && sliderSameParents(node, anchor.nodeParents) &&
        String(node.id || '') === anchor.nodeId &&
        node.closest('.nc-container, .nc_wrapper') === anchor.group &&
        (!track || (sliderSameParents(track, anchor.trackParents) &&
            String(track.id || '') === anchor.trackId &&
            track.closest('.nc-container, .nc_wrapper') === anchor.group));
}
function sliderTrackRect(track, handle, offsetX, offsetY) {
    if (!track || !verificationElementVisible(track)) return null;
    var r = track.getBoundingClientRect();
    if (r.width <= 50 || r.height <= 5) return null;
    // offsetLeft is usable only when it is relative to this actual track.
    var localOffset = handle && handle !== track && handle.offsetParent === track;
    return {left:r.left+offsetX, top:r.top+offsetY, width:r.width, height:r.height,
        offsetWidth:track.offsetWidth,
        handleOffsetLeft:localOffset ? handle.offsetLeft : null,
        handleOffsetWidth:localOffset ? handle.offsetWidth : null};
}
"""


def geometry_expression(slider_selectors, track_selectors, *, binding_key=None):
    """No cross-call geometry cache; an optional expiring reference anchors OS input."""
    return (
        (
            "(function() {\n"
            + GEOMETRY_HELPERS
            + r"""
    var sliders = __SLIDERS__, tracks = __TRACKS__, key = __KEY__;
    var found = visitAccessibleDocuments(function(doc, x, y, context) {
        var selected = selectedSlider(doc, sliders);
        if (!selected) return null;
        var handle = selected.node;
        var frame = doc.defaultView && doc.defaultView.frameElement;
        x += frame ? frame.clientLeft || 0 : 0;
        y += frame ? frame.clientTop || 0 : 0;
        var track = sliderTrack(doc, handle, tracks, sliders), r = handle.getBoundingClientRect();
        var result = {found:true, x:r.left+x, y:r.top+y, width:r.width, height:r.height,
            selector:selected.selector, context:context,
            track_rect:sliderTrackRect(track, handle, x, y)};
        if (key) {
            var anchor = {node:handle, doc:doc, frame:frame || null, track:track,
                nodeParents:sliderParents(handle), trackParents:track ? sliderParents(track) : null,
                nodeId:String(handle.id || ''), trackId:track ? String(track.id || '') : null,
                group:handle.closest('.nc-container, .nc_wrapper'), expiresAt:Date.now()+30000};
            window[key] = anchor;
            anchor.expiry = setTimeout(function() {
                if (window[key] === anchor) delete window[key];
            }, 30000);
            result.binding_key = key;
        }
        return result;
    }, true);
    if (found || key) return found;
    // Standalone track inspection remains available when there is no slider.
    return visitAccessibleDocuments(function(doc, x, y) {
        var frame = doc.defaultView && doc.defaultView.frameElement;
        var rect = sliderTrackRect(sliderTracks(doc, tracks)[0], null,
            x+(frame ? frame.clientLeft || 0 : 0), y+(frame ? frame.clientTop || 0 : 0));
        return rect ? {track_rect:rect} : null;
    }, true);
})()
"""
        )
        .replace("__SLIDERS__", json.dumps(slider_selectors))
        .replace("__TRACKS__", json.dumps(track_selectors))
        .replace("__KEY__", json.dumps(binding_key))
    )
