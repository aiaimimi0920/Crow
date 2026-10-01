// ==UserScript==
// @name         Taobao NC Captcha Auto Solver
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Auto solve Taobao NC slider captcha
// @match        *://*.taobao.com/*
// @match        *://sf.taobao.com/*
// @match        *://sf-item.taobao.com/*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    console.log('[NC-Solver] Script loaded');

    // Listen for solve command from external
    window.addEventListener('message', function(event) {
        if (event.source !== window || event.origin !== window.location.origin) return;
        if (event.data && event.data.type === 'SOLVE_NC_CAPTCHA') {
            console.log('[NC-Solver] Received solve command');
            solveNCCaptcha();
        }
    });

    // Auto-solve on page load if captcha detected
    setTimeout(function() {
        if (detectNCCaptcha()) {
            console.log('[NC-Solver] NC captcha detected, auto-solving...');
            solveNCCaptcha();
        }
    }, 2000);

    function detectNCCaptcha() {
        return !!(document.querySelector('#nc_1_n1z') ||
                  document.querySelector('.nc-container') ||
                  document.querySelector('.btn_slide'));
    }

    function solveNCCaptcha() {
        // Try to find NC instance
        var ncIns = window.NoCaptcha || window.nc_token;

        if (ncIns && ncIns._captchaIns) {
            console.log('[NC-Solver] Found NC instance via window');
            triggerNCSuccess(ncIns._captchaIns);
            return;
        }

        // Find slider element
        var slider = document.querySelector('#nc_1_n1z') ||
                     document.querySelector('.btn_slide') ||
                     document.querySelector('.nc-slider-btn');

        if (!slider) {
            console.log('[NC-Solver] Slider not found');
            return;
        }

        var track = document.querySelector('#nc_1_n1t') ||
                    document.querySelector('.nc_scale') ||
                    slider.parentElement;

        if (!track) {
            console.log('[NC-Solver] Track not found');
            return;
        }

        console.log('[NC-Solver] Starting drag simulation');

        var sliderRect = slider.getBoundingClientRect();
        var trackRect = track.getBoundingClientRect();

        var startX = sliderRect.left + sliderRect.width / 2;
        var startY = sliderRect.top + sliderRect.height / 2;
        var distance = trackRect.width - sliderRect.width - 4;

        // Simulate real mouse events with touches
        simulateRealDrag(slider, startX, startY, distance);
    }

    function simulateRealDrag(element, startX, startY, distance) {
        console.log('[NC-Solver] Simulating drag:', {startX, startY, distance});

        // Try direct DOM manipulation first
        var slider = element;
        var track = slider.parentElement;

        // Method 1: Direct style manipulation
        try {
            var finalLeft = distance + 'px';
            slider.style.left = finalLeft;
            slider.style.transform = 'translateX(' + distance + 'px)';
            console.log('[NC-Solver] Applied direct style');
        } catch (e) {
            console.log('[NC-Solver] Direct style failed:', e);
        }

        // Method 2: Dispatch real events with proper coordinates
        var rect = slider.getBoundingClientRect();
        var trackRect = track.getBoundingClientRect();

        // Generate path
        var events = [];
        var steps = Math.floor(distance / 3);
        var duration = 1200 + Math.random() * 800;

        for (var i = 0; i <= steps; i++) {
            var progress = i / steps;
            var easeProgress = 1 - Math.pow(1 - progress, 2);

            var x = startX + distance * easeProgress;
            var y = startY + (Math.random() - 0.5) * 4;

            events.push({x: x, y: y, time: duration * progress});
        }

        var startTime = Date.now();
        var currentIndex = 0;

        // Dispatch initial events
        dispatchMouseEvent(slider, 'mousedown', startX, startY);
        dispatchTouchEvent(slider, 'touchstart', startX, startY);

        // Also dispatch on document
        dispatchMouseEvent(document, 'mousedown', startX, startY);

        function moveNext() {
            if (currentIndex >= events.length) {
                var finalEvent = events[events.length - 1];
                dispatchMouseEvent(slider, 'mouseup', finalEvent.x, finalEvent.y);
                dispatchMouseEvent(document, 'mouseup', finalEvent.x, finalEvent.y);
                dispatchTouchEvent(slider, 'touchend', finalEvent.x, finalEvent.y);

                console.log('[NC-Solver] Drag sequence completed');

                // Try to trigger NC callback directly
                setTimeout(function() {
                    tryTriggerNCCallback();

                    // Check result
                    setTimeout(function() {
                        checkSuccess();
                    }, 500);
                }, 500);

                return;
            }

            var event = events[currentIndex];
            var elapsed = Date.now() - startTime;

            if (elapsed >= event.time) {
                dispatchMouseEvent(slider, 'mousemove', event.x, event.y);
                dispatchMouseEvent(document, 'mousemove', event.x, event.y);
                dispatchTouchEvent(slider, 'touchmove', event.x, event.y);
                currentIndex++;
            }

            requestAnimationFrame(moveNext);
        }

        requestAnimationFrame(moveNext);
    }

    function tryTriggerNCCallback() {
        // Try multiple ways to trigger success
        try {
            // Look for NC global object
            if (window.NoCaptcha && window.NoCaptcha._instances) {
                for (var key in window.NoCaptcha._instances) {
                    var instance = window.NoCaptcha._instances[key];
                    if (instance && instance.success) {
                        console.log('[NC-Solver] Calling NC instance success');
                        instance.success({
                            sig: 'mock_sig_' + Date.now(),
                            token: 'mock_token_' + Date.now(),
                            csessionid: 'mock_session'
                        });
                    }
                }
            }

            // Try nc_token
            if (window.nc_token && window.nc_token._captchaIns) {
                console.log('[NC-Solver] Found nc_token');
                if (window.nc_token._captchaIns.success) {
                    window.nc_token._captchaIns.success();
                }
            }

            // Dispatch custom event
            document.dispatchEvent(new CustomEvent('nc-success', {
                detail: {solved: true, timestamp: Date.now()}
            }));

        } catch (e) {
            console.log('[NC-Solver] Callback trigger error:', e);
        }
    }

    function checkSuccess() {
        var container = document.querySelector('.nc-container');
        var hasSuccess = container && container.className.indexOf('nc-success') >= 0;

        if (!hasSuccess) {
            // Check by text
            hasSuccess = document.body.innerText.indexOf('验证通过') >= 0 ||
                        document.body.innerText.indexOf('通过验证') >= 0;
        }

        if (hasSuccess) {
            console.log('[NC-Solver] ✅ SUCCESS!');
            window.postMessage({type: 'NC_SOLVED', success: true}, window.location.origin);
        } else {
            console.log('[NC-Solver] ❌ Failed, will retry...');
            window.postMessage({type: 'NC_SOLVED', success: false}, window.location.origin);

            // Retry after delay
            setTimeout(function() {
                if (detectNCCaptcha()) {
                    console.log('[NC-Solver] Retrying...');
                    solveNCCaptcha();
                }
            }, 2000);
        }
    }

    function dispatchMouseEvent(element, type, clientX, clientY) {
        var event = new MouseEvent(type, {
            view: window,
            bubbles: true,
            cancelable: true,
            clientX: clientX,
            clientY: clientY,
            screenX: clientX,
            screenY: clientY,
            button: 0,
            buttons: type === 'mousedown' || type === 'mousemove' ? 1 : 0
        });
        element.dispatchEvent(event);
    }

    function dispatchTouchEvent(element, type, clientX, clientY) {
        var touch = new Touch({
            identifier: 1,
            target: element,
            clientX: clientX,
            clientY: clientY,
            screenX: clientX,
            screenY: clientY,
            pageX: clientX,
            pageY: clientY
        });

        var event = new TouchEvent(type, {
            view: window,
            bubbles: true,
            cancelable: true,
            touches: type === 'touchend' ? [] : [touch],
            targetTouches: type === 'touchend' ? [] : [touch],
            changedTouches: [touch]
        });

        element.dispatchEvent(event);
    }

    function triggerNCSuccess(instance) {
        try {
            if (instance.success && typeof instance.success === 'function') {
                instance.success();
                console.log('[NC-Solver] ✅ Called NC success callback');
                return true;
            }
        } catch (e) {
            console.log('[NC-Solver] Failed to call success:', e);
        }
        return false;
    }

    // Export function for external call
    window.solveNCCaptcha = solveNCCaptcha;

    console.log('[NC-Solver] Ready. Call window.solveNCCaptcha() or send message to trigger.');
})();
