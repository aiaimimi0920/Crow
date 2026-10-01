// ==UserScript==
// @name         法拍房全能助手 (Fapaifang Unified Tool)
// @namespace    http://tampermonkey.net/
// @version      1.1
// @description  Crow 统一采集助手：集成嗅探、检阅（快/慢）和详情助手功能
// @author       Antigravity
// @match        https://sf.taobao.com/*
// @match        https://sf-item.taobao.com/*
// @match        https://susong-item.taobao.com/*
// @match        https://paimai.taobao.com/pmp_item/*
// @match        https://login.taobao.com/*
// @match        https://sec.taobao.com/*
// @connect      127.0.0.1
// @connect      localhost
// @connect      sf.taobao.com
// @connect      sf-item.taobao.com
// @connect      susong-item.taobao.com
// @connect      detail-ext.taobao.com
// @connect      itemcdn.tmall.com
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_listValues
// @grant        GM_deleteValue
// @grant        GM_addValueChangeListener
// @grant        GM_openInTab
// @grant        GM_registerMenuCommand
// @grant        GM_info
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    const initialUrlParams = new URLSearchParams(window.location.search);
    const urlPort = initialUrlParams.get('uni_port');
    const configuredPort = String(GM_getValue('uni_api_port', '8001'));
    const API_PORT = String(urlPort || configuredPort);
    function validApiPort(value) {
        return /^[1-9][0-9]{0,4}$/.test(value) && Number(value) <= 65535;
    }
    if (!validApiPort(API_PORT) || !validApiPort(configuredPort)) {
        throw new Error('Invalid collection API port');
    }
    const API_BASE = `http://127.0.0.1:${API_PORT}/api`;
    const CREDENTIAL_KEY = 'uni_collection_credential';
    const OPERATOR_CREDENTIAL_KEY = 'uni_operator_credential';
    const OPERATOR_PATHS = new Set(['/collection/control/resume', '/approve_area']);
    const EMPTY_POST_PATHS = new Set([
        '/collection/seeds/next_task', '/collection/details/tasks',
        '/collection/details/next_task', '/get_next_task', ...OPERATOR_PATHS,
    ]);

    function configureCredential(key, role) {
        const origin = new URL(`http://127.0.0.1:${configuredPort}`).origin;
        const value = window.prompt(`Crow ${role} token for ${origin}/api (cancel to keep current):`, '');
        if (value === null) return;
        const token = value.trim();
        if (!/^[A-Za-z0-9_-]{32,512}$/.test(token)) {
            log('Invalid collection credential; existing value retained', 'error');
            return;
        }
        const otherKey = key === CREDENTIAL_KEY ? OPERATOR_CREDENTIAL_KEY : CREDENTIAL_KEY;
        if (GM_getValue(otherKey, null)?.token === token) {
            log('Worker and operator credentials must be distinct', 'error');
            return;
        }
        GM_setValue(key, { origin, token });
        log(`Crow ${role} credential saved for configured API port`, 'info');
    }
    GM_registerMenuCommand('Configure Crow collection credential', () => configureCredential(CREDENTIAL_KEY, 'worker'));
    GM_registerMenuCommand('Configure Crow operator credential', () => configureCredential(OPERATOR_CREDENTIAL_KEY, 'operator'));

    function apiRequestHeaders(endpoint, method) {
        if (typeof endpoint !== 'string' || !endpoint.startsWith('/') || /[\\\s#]/.test(endpoint)) {
            throw new Error('Invalid collection API endpoint');
        }
        const pathname = endpoint.split('?')[0];
        if (!/^\/[A-Za-z0-9_/-]+$/.test(pathname) || pathname.includes('//')) {
            throw new Error('Invalid collection API path');
        }
        const target = new URL(API_BASE + endpoint);
        const headers = { 'Content-Type': 'application/json' };
        const operator = OPERATOR_PATHS.has(pathname);
        const credential = GM_getValue(operator ? OPERATOR_CREDENTIAL_KEY : CREDENTIAL_KEY, null);
        if (credential === null) {
            if (method === 'POST') throw new Error('Collection credential is not configured');
            return headers;
        }
        if (typeof credential !== 'object' || credential.origin !== target.origin
            || typeof credential.token !== 'string' || !/^[A-Za-z0-9_-]{32,512}$/.test(credential.token)) {
            throw new Error('Collection credential does not match API destination');
        }
        // Older managers can silently ignore redirect:error and forward a secret.
        const version = typeof GM_info === 'object' && /^(\d+)\.(\d+)(?:\.|$)/.exec(GM_info.version);
        if (!version || GM_info.scriptHandler !== 'Tampermonkey'
            || !(Number(version[1]) > 5 || (Number(version[1]) === 5 && Number(version[2]) >= 5))) {
            throw new Error('Collection credentials require Tampermonkey 5.5 or newer');
        }
        headers[operator ? 'X-FAPAI-Control-Token' : 'X-FAPAI-Collection-Token'] = credential.token;
        return headers;
    }
    
    log(`[Init] Using API Port: ${API_PORT} ${urlPort ? '(from URL)' : '(from Config)'}`, 'info');


    // --- API Helper ---
    function fetchApi(endpoint, data = {}, callback = null, errorCallback = null) {
        let method;
        let headers;
        try {
            if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid API body');
            method = Object.keys(data).length > 0 || EMPTY_POST_PATHS.has(endpoint.split('?')[0]) ? "POST" : "GET";
            headers = apiRequestHeaders(endpoint, method);
        } catch (error) {
            log('API credential or destination rejected', 'error');
            if (errorCallback) errorCallback();
            return;
        }
        let settled = false;
        let request;
        let timer;
        const fail = () => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            log('API request failed', 'error');
            if (errorCallback) errorCallback();
        };
        // fetch-backed GM requests do not honor timeout on every browser.
        timer = setTimeout(() => {
            try {
                fail();
            } finally {
                if (request) request.abort();
            }
        }, 30000);
        try {
            request = GM_xmlhttpRequest({
            method: method,
            url: API_BASE + endpoint,
            headers,
            redirect: 'error',
            anonymous: true,
            data: method === "POST" ? JSON.stringify(data) : null,
            onload: function(response) {
                if (settled) return;
                if (response.finalUrl && response.finalUrl !== API_BASE + endpoint) {
                    fail();
                    return;
                }
                if (response.status === 200) {
                    let json;
                    try {
                        json = JSON.parse(response.responseText);
                    } catch (error) {
                        fail();
                        return;
                    }
                    settled = true;
                    clearTimeout(timer);
                    if (callback) callback(json);
                } else {
                    fail();
                }
            },
            onerror: fail,
            onabort: fail,
            ontimeout: fail,
            });
        } catch (error) {
            fail();
        }
    }

    function formatLocalDateTime(input) {
        const d = new Date(input);
        if (Number.isNaN(d.getTime())) return '';
        const pad = (v) => String(v).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }

    // ==========================================
    // MODULE 1: SNIFFING (Master Page)
    // ==========================================
    let sniffState = {
        maxSlots: 3, // Concurrency for sniffing (3 tabs)
        interval: 3000,
        running: false,
        workerMode: false,
        currSessionIdx: 0
    };

    // Use multiple sessions to maximize distribution across locations
    let sniffSessions = [];
    try {
        const stored = sessionStorage.getItem('sniff_sessions_list');
        if (stored) sniffSessions = JSON.parse(stored);
    } catch(e) {}

    if (!sniffSessions || sniffSessions.length < sniffState.maxSlots) {
        sniffSessions = [];
        for (let i = 0; i < sniffState.maxSlots; i++) {
            sniffSessions.push('sniff_s' + i + '_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5));
        }
        sessionStorage.setItem('sniff_sessions_list', JSON.stringify(sniffSessions));
    }
    
    // Auto-resume sniffing if reloading (Master only)
    if (sessionStorage.getItem("uni_is_sniffing") === "true") {
        window.addEventListener('load', () => {
             setTimeout(() => {
                 if (document.getElementById('uni-mode-select')) {
                     document.getElementById('uni-mode-select').value = 'SNIFF';
                     currentMode = 'SNIFF';
                     GM_setValue('unified_mode', 'SNIFF'); // Sync
                     toggleRunState(); // Auto-start
                 }
             }, 1000);
        });
    }

    // --- Optimization: No-Image Mode (for Sniffing/Review) ---
    function injectOptimization() {
        const style = document.createElement('style');
        style.textContent = `
            img, [style*="background-image"], .lazyload, .lazy-img, 
            .item-img, .item-pic, .image-gallery, .J_ItemPic,
            video, iframe[src*="video"], .video-container,
            #J_Map, .show-amap, iframe[src*="gaode"], iframe[src*="amap"],
            #J_SiteFooter, .tb-footer, #sf-foot-2014, .sf-foot-2014,
            .pm-main-l, #J_UlThumb, .J_HeadImageWrap,
            #J_SiteNav, .site-nav, #sf-head-2014, .sf-head-2014, .nav-con {
                visibility: hidden !important;
                height: 0 !important;
                min-height: 0 !important;
                max-height: 0 !important;
                overflow: hidden !important;
            }
        `;
        document.head.appendChild(style);

        const imgObserver = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.tagName === 'IMG') {
                        node.src = '';
                        node.srcset = '';
                        node.loading = 'lazy';
                    }
                }
            }
        });
        imgObserver.observe(document.documentElement, { childList: true, subtree: true });
        log('[Optimization] No-Image Mode Active', 'info');
    }

    // Determine current mode early
    const modeParam = initialUrlParams.get('uni_mode');
    const autoStartParam = initialUrlParams.get('uni_autostart') === '1';

    // Auto-Run Workers (Sniff Worker)
    if (modeParam === 'SNIFF_WORKER') {
        injectOptimization();
        window.addEventListener('load', () => {
            setTimeout(startSniffWorker, 1000);
        });
    }
