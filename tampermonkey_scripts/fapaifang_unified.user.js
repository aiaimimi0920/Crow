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
    function startSniffing() {
        if (modeParam === 'SNIFF_WORKER') {
            startSniffWorker();
        } else {
            startSniffMaster();
        }
    }
    
    function startSniffMaster() {
        log('启动嗅探主控 (Master)...', 'info');
        sessionStorage.setItem("uni_is_sniffing", "true");
        sniffState.running = true;
        sniffMasterLoop();
    }
    
    function stopSniffing() {
        sessionStorage.setItem("uni_is_sniffing", "false");
        sniffState.running = false;
    }
    
    function sniffMasterLoop() {
        if (!isRunning || currentMode !== 'SNIFF' || !sniffState.running) return;

        // Count active slots
        const openTabs = getActiveSlots('sniff_tab_');
        const status = document.getElementById('uni-stats-text');
        if (status) status.innerText = `Sniffing: ${openTabs.length}/${sniffState.maxSlots} Tabs`;

        if (openTabs.length < sniffState.maxSlots) {
             // Rotate session to distribute load across locations
             const sessionId = sniffSessions[sniffState.currSessionIdx % sniffSessions.length];
             sniffState.currSessionIdx++;

             fetchApi('/collection/seeds/next_task', { session_id: sessionId }, (res) => {
                if (res.task && res.task.url) {
                    log(`分配任务: ${res.task.desc || res.task.url}`, 'success');
                    
                    const workerUrl = new URL(res.task.url);
                    workerUrl.searchParams.set('uni_mode', 'SNIFF_WORKER');
                    
                    const tabName = 'sniff_tab_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
                    GM_setValue(tabName, Date.now()); 
                    
                    GM_openInTab(workerUrl.toString(), { active: false, insert: true });
                } else {
                    // No task?
                }
                setTimeout(sniffMasterLoop, sniffState.interval);
             }, () => setTimeout(sniffMasterLoop, sniffState.interval));
        } else {
             setTimeout(sniffMasterLoop, 1000);
        }
    }

    function getActiveSlots(prefix) {
        const now = Date.now();
        const keys = GM_listValues();
        let active = [];
        for (let key of keys) {
            if (key.startsWith(prefix)) {
                const ts = GM_getValue(key);
                if (now - ts < 90000) { 
                    active.push(key);
                } else {
                    GM_deleteValue(key);
                }
            }
        }
        return active;
    }

    function startSniffWorker() {
        log('启动嗅探工作者 (Worker)...', 'info');
        sniffLoopLocal();
    }
    
    function sniffLoopLocal() {
        log("开始滚动页面 (模拟人类操作)...", 'info');
        let steps = 0;
        const maxSteps = 50;
        
        const randomScroll = () => {
             const scrollHeight = document.documentElement.scrollHeight || document.body.scrollHeight;
             const currentPos = window.scrollY + window.innerHeight;
             
             const isNoResult = document.body && (document.body.innerText.includes('很抱歉，没有您要找的标的物') || document.body.innerText.includes('很抱歉'));
             
             if (currentPos >= scrollHeight - 100 || steps > maxSteps || isNoResult) {
                 log("滚动/检查完成，开始解析数据...", 'success');
                 scrapeAndSave((hasZeroBid, isListEmpty) => {
                     checkForNextPageAndReport(hasZeroBid, isListEmpty || isNoResult);
                     log('任务完成，关闭标签页...', 'success');
                     setTimeout(() => window.close(), 1000);
                 });
                 return;
             }
             
             steps++;
             const distance = Math.floor(Math.random() * 300) + 150;
             window.scrollBy({ top: distance, behavior: 'smooth' });
             setTimeout(randomScroll, Math.floor(Math.random() * 500) + 300);
        };
        randomScroll();
    }

    // Placeholder for fetchNextSniffTask since it was removed
    function fetchNextSniffTask() {}
    
    function checkForNextPageAndReport(hasZeroBid = false, isListEmpty = false) {
        // Logic to determine if there is a next page based on URL and DOM
        // This is simplified for brevity; full logic mirrors taobao_monitor
        let pageNum = 1;
        const url = new URL(window.location.href);
        const p = url.searchParams.get('page');
        if (p) pageNum = parseInt(p);
        
        let isNoResultText = false;
        if (document.body && (document.body.innerText.includes('很抱歉，没有您要找的标的物') || document.body.innerText.includes('很抱歉'))) {
             isNoResultText = true;
        }

        const items = document.querySelectorAll('.sf-item-list li, .pai-item');
        const hasItems = items.length > 0;
        let hasNext = hasItems && !hasZeroBid && !isNoResultText && !isListEmpty; 
        
        // Report status to backend (to advance collection search task state)
        fetchApi('/collection/seeds/report_progress', {
            url: window.location.href,
            has_next: hasNext,
            is_empty: !hasNext || isListEmpty || isNoResultText,
            page_num: pageNum,
            zero_bid_detected: hasZeroBid
        });
    }
    
    function scrapeAndSave(onDone) {
        const scriptData = document.getElementById('sf-item-list-data');
        if (scriptData) {
            try {
                const json = JSON.parse(scriptData.innerText);
                if (json.data && Array.isArray(json.data)) {
                        const totalRaw = json.data.length;
                        const isListEmpty = (totalRaw === 0);
                        
                        // Check for zero-bid items
                        const hasZeroBidItem = json.data.some(item => item.bidCount === 0);
                        if (hasZeroBidItem) {
                            log(`[剪枝] 发现0出价物品`, 'warning');
                        }
                        
                        // Filter: status == 'done' AND bidCount >= 1
                        const items = json.data
                        .filter(item => item.status === 'done' && item.bidCount >= 1)
                        .map(item => ({
                            id: item.id,
                            title: item.title,
                            currentPrice: item.currentPrice,
                            initialPrice: item.initialPrice,
                            auction_date: formatLocalDateTime(item.end),
                            auction_start_time: formatLocalDateTime(item.startTime),
                            end: item.end, 
                            url: item.itemUrl ? "https:" + item.itemUrl : "",
                            status: item.status,
                            bidCount: item.bidCount,
                            bidderCount: item.bidUserNumber ?? item.bidderCount,
                            applyCount: item.applyCount,
                            watchCount: item.watchCount ?? item.pv,
                            remindCount: item.remindCount ?? item.reminderCount,
                            viewCount: item.viewCount ?? item.pv,
                            location: item.itemAddress || item.address || item.location,
                            full_address: item.itemAddress || item.address || item.location,
                            district: item.district,
                            city: item.city,
                            latitude: item.latitude ?? item.lat,
                            longitude: item.longitude ?? item.lng,
                            coordinate_source: (item.latitude ?? item.lat) != null && (item.longitude ?? item.lng) != null ? 'list' : undefined,
                            auction_round: item.auctionRound ?? item.round,
                            housing_type: item.housingType || item.categoryName,
                            deposit: item.deposit,
                            is_processed: false 
                        }));
                        
                        if (items.length > 0) {
                            log(`发现 ${items.length} 个有效(已成交)物品，保存中...`, 'success');
                            fetchApi('/collection/seeds/batch', { items: items, raw_payload: json.data, source_page_url: window.location.href }, (res) => {
                                log(`[Sniff] 保存成功: ${res.new} 新增`, 'success');
                                // Auto-resume server if it was paused (User solved captcha manually)
                                resumeServer(true);
                                if (onDone) onDone(hasZeroBidItem, isListEmpty);
                            }, () => {
                                log("保存失败!", 'error');
                                if (onDone) onDone(hasZeroBidItem, isListEmpty);
                            });
                        } else {
                            log("本页无有效成交物品", 'info');
                            if (onDone) onDone(hasZeroBidItem, isListEmpty);
                        }
                } else {
                    if (onDone) onDone(false, true); // No data means empty
                }
            } catch (e) { 
                log("JSON解析失败", 'error'); 
                if (onDone) onDone(false, true); // Error parsing implies we don't have good data, safer to treat as empty to prevent loops
            }
        } else {
             log("未找到数据脚本 (sf-item-list-data)", 'error');
             if (onDone) onDone(false, true); // No script means empty
        }
    }
    
    // --- State Management ---
    // Mode: 'IDLE' | 'SNIFF' | 'REVIEW_FAST' | 'REVIEW_SLOW'
    let currentMode = GM_getValue('unified_mode', 'IDLE');
    // 当页面通过 URL 指定模式时，优先使用页面模式（避免双开页面互相覆盖全局模式）
    if (modeParam === 'SNIFF' || modeParam === 'REVIEW_FAST' || modeParam === 'REVIEW_SLOW' || modeParam === 'IDLE') {
        currentMode = modeParam;
    }
    let isRunning = false;
    let dashboardPanel = null;
    
    // Page Type Detection
    const isMaster = window.location.hostname === "sf.taobao.com";
    const isDetail = ["sf-item.taobao.com", "susong-item.taobao.com", "paimai.taobao.com"].includes(window.location.hostname);
    const isLoginOrSec = ["login.taobao.com", "sec.taobao.com"].includes(window.location.hostname);

    const urlParams = initialUrlParams; // Reuse parsed params
    const autoWorkerMode = urlParams.get('auto_worker'); // 1 = enabled

    // --- Captcha Detector Helpers ---
    function hasCaptchaChallenge(doc = document) {
        try {
            const selectors = [
                '#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]',
                '#nocaptcha', '.nc-container', '.nc_wrapper', '.nc_scale',
                '[id^="nc_"][id$="_n1t"]', '.btn_slide', '.nc_iconfont.btn_slide'
            ];

            const isVisible = (el) => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                return el.offsetParent !== null && rect.width > 2 && rect.height > 2;
            };

            for (const sel of selectors) {
                const el = doc.querySelector(sel);
                if (isVisible(el)) return true;
            }

            const bodyText = doc.body ? (doc.body.innerText || '') : '';
            if (bodyText.includes('RGV587_ERROR')) return true;

            const frames = doc.querySelectorAll('iframe');
            for (const frame of frames) {
                try {
                    const fd = frame.contentDocument;
                    if (!fd) continue;
                    for (const sel of selectors) {
                        const fel = fd.querySelector(sel);
                        if (isVisible(fel)) return true;
                    }
                    const fText = fd.body ? (fd.body.innerText || '') : '';
                    if (fText.includes('RGV587_ERROR')) return true;
                } catch(e) {}
            }
        } catch(e) {}
        return false;
    }

    // --- Worker Logging Helper ---
    function logToMaster(msg, type = 'info') {
        // Logs locally
        console.log(`[Worker] ${msg}`);
        // Sends to Master via shared storage
        GM_setValue('uni_worker_log', {
            ts: Date.now(),
            msg: `[Worker] ${msg}`,
            type: type
        });
    }

    // --- Logger ---
    function log(msg, type = 'info') {
        const time = new Date().toLocaleTimeString();
        console.log(`[Unified] [${type.toUpperCase()}] ${msg}`);
        
        // Update Dashboard Log if exists
        const logEl = document.getElementById('uni-log-content');
        if (logEl) {
            const line = document.createElement('div');
            line.style.borderBottom = '1px solid #333';
            line.style.padding = '2px 0';
            line.style.color = type === 'error' ? '#ff6b6b' : (type === 'success' ? '#51cf66' : '#ddd');
            line.textContent = `[${time}] ${msg}`;
            logEl.appendChild(line);
            logEl.scrollTop = logEl.scrollHeight;
            
            // Limit log lines
            if (logEl.children.length > 50) logEl.removeChild(logEl.firstChild);
        }
    }

    function refreshGlobalStats() {
        fetchApi('/status', {}, (res) => {
            const el = document.getElementById('uni-global-stats');
            const statusEl = document.getElementById('uni-status-text');
            const startBtn = document.getElementById('uni-btn-start');
            const resumeBtn = document.getElementById('uni-btn-resume');

            if (res.paused) {
                if(statusEl) {
                    statusEl.textContent = '🛑 服务暂停 (无需验证码)';
                    statusEl.style.color = '#ff6b6b';
                }
                if(resumeBtn) resumeBtn.style.display = 'block';
                if(startBtn) startBtn.style.display = 'none';
            } else {
                if(statusEl) {
                    if (statusEl.innerText.includes("暂停") || statusEl.innerText.includes("Running")) {
                         statusEl.textContent = isRunning ? '运行中...' : '已就绪';
                         statusEl.style.color = isRunning ? '#51cf66' : '#ffd43b';
                    }
                }
                if(resumeBtn) resumeBtn.style.display = 'none';
                if(startBtn) startBtn.style.display = 'block';

                GM_deleteValue('last_captcha_global_time');
                GM_deleteValue('captcha_solving_tab_id');
                GM_deleteValue('captcha_solving_tab_id');
            }

            if (el) {
                el.innerHTML = `📊 总量: <span style="color:white">${res.total_ids || 0}</span> | 📝 已探测: <span style="color:#ffec99">${res.captured_count || 0}</span> | 🤖 AI定稿: <span style="color:#63e6be">${res.ai_finalized_count || 0}</span>`;
            }
        }, () => {
             // Squelch errors for stats to avoid log spam
        });
    }

    function resumeServer(isAuto) {
        fetchApi('/collection/control/resume', {}, () => {
             if (!isAuto) {
                 log('✅ 服务已恢复 (Resumed)', 'success');
                 refreshGlobalStats();
             } else {
                 refreshGlobalStats();
             }
        });
    }

    // --- Dashboard UI (Only on Master Page) ---
    function createDashboard() {
        if (!isMaster || dashboardPanel) return;
        if (modeParam === 'SNIFF_WORKER') return; // Hide dashboard in worker tabs

        dashboardPanel = document.createElement('div');
        Object.assign(dashboardPanel.style, {
            position: 'fixed', top: '10px', right: '10px', width: '300px',
            backgroundColor: 'rgba(0, 0, 0, 0.85)', color: 'white',
            borderRadius: '8px', padding: '15px', zIndex: 999999,
            fontFamily: 'Segoe UI, sans-serif', fontSize: '14px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.5)', border: '1px solid #444'
        });

        const render = () => {
            const modeOptions = [
                { val: 'IDLE', label: '🛑 空闲 (Idle)' },
                { val: 'SNIFF', label: '🕵️ 嗅探模式 (Sniffing)' },
                { val: 'REVIEW_FAST', label: '⚡ 快速检阅 (Fast API)' },
                { val: 'REVIEW_SLOW', label: '🐢 慢速检阅 (Slow Tab)' }
            ];
            
            let optionsHtml = modeOptions.map(opt => 
                `<option value="${opt.val}" ${currentMode === opt.val ? 'selected' : ''}>${opt.label}</option>`
            ).join('');

            dashboardPanel.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; border-bottom:1px solid #555; padding-bottom:8px;">
                    <strong style="font-size:16px; color:#4dabf7;">🛠️ 法拍房全能助手</strong>
                    <span style="font-size:12px; color:#888;">v1.0</span>
                </div>
                
                <div style="margin-bottom:12px;">
                    <label style="display:block; margin-bottom:5px; color:#ccc;">工作模式:</label>
                    <select id="uni-mode-select" style="width:100%; padding:6px; background:#333; color:white; border:1px solid #555; border-radius:4px;">
                        ${optionsHtml}
                    </select>
                </div>

                <div style="display:flex; gap:10px; margin-bottom:15px;">
                    <button id="uni-btn-start" style="flex:1; padding:8px; background:${isRunning ? '#f03e3e' : '#2f9e44'}; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;">
                        ${isRunning ? '⏹️ 停止工作' : '▶️ 开始工作'}
                    </button>
                    <button id="uni-btn-resume" style="display:none; flex:1; padding:8px; background:#e67700; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold; animation: pulse 2s infinite;">
                        ⚠️ 恢复服务 (Resume)
                    </button>
                    <button id="uni-btn-force-unlock" style="padding:8px; background:#e03131; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;" title="当系统卡在验证码状态时，强制解除锁定">
                        🛠️ 解锁拉平
                    </button>
                    <button id="uni-btn-worker" style="padding:8px; background:#673ab7; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:bold;" title="打开验证码专属打工页面">
                        🤖 解密页
                    </button>
                    <button id="uni-btn-dual" style="padding:8px; background:#1c7ed6; color:white; border:none; border-radius:4px; cursor:pointer;" title="一键双开：嗅探+快速检阅（自动启动）">
                        🚀 双开
                    </button>
                </div>

                <div id="uni-stats-area" style="margin-bottom:10px; font-size:12px; color:#aaa; line-height:1.5;">
                    <div>状态: <span id="uni-status-text" style="color:${isRunning ? '#51cf66' : '#ffd43b'}">${isRunning ? '运行中' : '已就绪'}</span></div>
                    <div>统计: <span id="uni-stats-text">0 成功 | 0 失败</span></div>
                    <div id="uni-global-stats" style="margin-top:4px; border-top:1px dashed #444; padding-top:4px; color:#8ce99a;">📊 初始化统计...</div>
                </div>

                <div style="background:#222; border:1px solid #444; border-radius:4px; padding:5px;">
                    <div id="uni-log-content" style="height:120px; overflow-y:auto; font-family:monospace; font-size:11px; white-space:pre-wrap;"></div>
                </div>
                
                <div style="margin-top:5px; font-size:10px; color:#666; text-align:right;">
                    API Port: <select id="uni-port-select" style="background:#333; color:#aaa; border:none;">
                        <option value="8001">8001 (Server)</option>
                        <option value="5001">5001 (Fixer)</option>
                    </select>
                </div>

                <style>
                @keyframes pulse {
                    0% { opacity: 1; transform: scale(1); }
                    50% { opacity: 0.8; transform: scale(0.98); }
                    100% { opacity: 1; transform: scale(1); }
                }
                </style>
            `;
            
            // Bind Events
            const portSelect = document.getElementById('uni-port-select');
            if (portSelect) {
                // Restore saved port
                const savedPort = GM_getValue('uni_api_port', '8001');
                portSelect.value = savedPort;
                // Update global constant-like variable (we need to change how API_BASE is used)
                // Since API_BASE is const, we need to refactor it to be dynamic or just reload
                portSelect.onchange = (e) => {
                    const newPort = e.target.value;
                    GM_setValue('uni_api_port', newPort);
                    log(`端口已切换至 ${newPort}，即将刷新页面...`, 'warning');
                    setTimeout(() => location.reload(), 1000);
                };
            }
            
            // Bind Events
            document.getElementById('uni-mode-select').onchange = (e) => {
                if (isRunning) {
                    alert('请先停止当前任务再切换模式');
                    e.target.value = currentMode;
                    return;
                }
                currentMode = e.target.value;
                GM_setValue('unified_mode', currentMode);
                render(); // Re-render to update UI context
            };

            document.getElementById('uni-btn-start').onclick = () => {
                toggleRunState();
            };
            
            document.getElementById('uni-btn-resume').onclick = () => {
                resumeServer(false);
            };
            
            const dualBtn = document.getElementById('uni-btn-dual');
            if (dualBtn) {
                dualBtn.onclick = () => {
                    const base = 'https://sf.taobao.com/';
                    const port = GM_getValue('uni_api_port', '8001');
                    const sniffUrl = `${base}?uni_mode=SNIFF&uni_autostart=1&uni_port=${encodeURIComponent(port)}`;
                    const fastUrl = `${base}?uni_mode=REVIEW_FAST&uni_autostart=1&uni_port=${encodeURIComponent(port)}`;

                    GM_openInTab(sniffUrl, { active: false, insert: true });
                    GM_openInTab(fastUrl, { active: false, insert: true });
                    log('🚀 已双开：嗅探 + 快速检阅（自动进入模式）', 'success');
                };
            }
            
            const workerBtn = document.getElementById('uni-btn-worker');
            if (workerBtn) workerBtn.onclick = () => window.open('https://sf.taobao.com/?__captcha_worker_master=1', '_blank', 'width=800,height=600');

            const btnForceUnlock = document.getElementById('uni-btn-force-unlock');
            if (btnForceUnlock) btnForceUnlock.onclick = forceUnlockCaptcha;
        };

        document.body.appendChild(dashboardPanel);
        render();
        log('面板已加载，等待指令...');

        // URL 自动启动：用于“打开即进入嗅探/快速检阅”
        if (autoStartParam && isMaster && (modeParam === 'SNIFF' || modeParam === 'REVIEW_FAST' || modeParam === 'REVIEW_SLOW')) {
            setTimeout(() => {
                if (!isRunning) {
                    const modeSelect = document.getElementById('uni-mode-select');
                    if (modeSelect) modeSelect.value = modeParam;
                    currentMode = modeParam;
                    toggleRunState();
                    log(`🚀 URL自动启动已执行: ${modeParam}`, 'success');
                }
            }, 1200);
        }
        
        // Listen for Worker Logs
        GM_addValueChangeListener('uni_worker_log', (name, oldVal, newVal, remote) => {
            if (remote && newVal) {
                log(newVal.msg, newVal.type);
            }
        });
        setInterval(refreshGlobalStats, 5000);
        refreshGlobalStats();
    }

    function toggleRunState() {
        isRunning = !isRunning;
        const btn = document.getElementById('uni-btn-start');
        const status = document.getElementById('uni-status-text');
        
        if (btn && status) {
            btn.textContent = isRunning ? '⏹️ 停止工作' : '▶️ 开始工作';
            btn.style.background = isRunning ? '#f03e3e' : '#2f9e44';
            status.textContent = isRunning ? '运行中...' : '已停止';
            status.style.color = isRunning ? '#51cf66' : '#ffd43b';
        }

        if (isRunning) {
            log(`启动模式: ${currentMode}...`, 'success');
            startLogic();
        } else {
            log('正在停止...', 'info');
            stopLogic();
        }
    }
    
    function forceUnlockCaptcha() {
        log('🛠️ 手动强制解除验证码锁定...', 'warning');
        fastReviewState.captchaMode = false;
        GM_setValue('uni_captcha_lock', 0);
        GM_setValue('uni_captcha_force_unlock', Date.now()); // Broadcast unlock to all worker tabs
        GM_deleteValue('uni_captcha_worker_active'); // Clean up any stale worker identities
        
        document.getElementById('uni-status-text').textContent = '已强制解锁';
        
        // AUTO-RESUME BACKEND
        fetchApi('/collection/control/resume', {}, () => {
             log('🔄 已通知服务器解除暂停状态', 'success');
             if (isRunning && currentMode === 'REVIEW_FAST') {
                 fastReviewLoop(); // Resume
             }
        });
    }

    // --- Logic Dispatcher ---
    function startLogic() {
        switch (currentMode) {
            case 'SNIFF':
                startSniffing();
                break;
            case 'REVIEW_FAST':
                startFastReview();
                break;
            case 'REVIEW_SLOW':
                startSlowReview();
                break;
            case 'IDLE':
            default:
                log('空闲模式，无操作');
                isRunning = false; // Reset
                break;
        }
    }

    function stopLogic() {
        // 停止 Fast Review 相关计时器，避免残留状态干扰下次启动
        if (fastReviewState.pulseTimer) {
            clearInterval(fastReviewState.pulseTimer);
            fastReviewState.pulseTimer = null;
        }
        if (fastReviewState.recoveryTimer) {
            clearInterval(fastReviewState.recoveryTimer);
            fastReviewState.recoveryTimer = null;
        }
        clearFastCaptchaTimers();
        fastReviewState.captchaMode = false;
        fastReviewState.captchaStartAt = 0;
        fastReviewState.recovering = false;
    }

    // ==========================================
    // MODULE 1: SNIFFING (Master Page)
    // ==========================================
    // Logic is implemented at the top of the file.

    // ==========================================
    // MODULE 2: FAST REVIEW (Master Page - No Tabs)
    // ==========================================
    let fastReviewState = {
        activeCount: 0,
        stats: { fetched: 0, success: 0, failed: 0 },
        concurrency: 100,    // Adaptive concurrency current value (aggressive profile initial)
        minConcurrency: 20,
        initialConcurrency: 100,
        maxConcurrency: 120,
        dropMultiplier: 0.75,
        recoverStep: 5,
        recoverIntervalMs: 30000,
        cooldownMs: 3 * 60 * 1000,
        lastCaptchaAt: 0,
        recoveryTimer: null,
        batchSize: 200,      // Larger refill size
        taskQueue: [],       // Local buffer
        fetching: false,     // Refill lock
        pulseTimer: null,
        captchaMode: false,
        captchaStartAt: 0,
        captchaHeartbeatTimer: null,
        captchaCheckTimer: null,
        captchaWatchdogTimer: null,
        captchaProbeFailCount: 0,
        recovering: false,
        manualPopupTimer: null,
        // Token Bucket Rate Limiter
        tokens: 0,
        tokenRate: 10,        // Emit max 10 requests per second
        lastTokenUpdate: 0
    };

    function startFastReview() {
        log('启动快速检阅 (流水线模式)...', 'info');
        fastReviewState.stats = { fetched: 0, success: 0, failed: 0 };
        fastReviewState.activeCount = 0;
        fastReviewState.taskQueue = [];
        fastReviewState.fetching = false;
        fastReviewState.captchaMode = false;
        fastReviewState.lastCaptchaAt = 0;
        fastReviewState.concurrency = fastReviewState.initialConcurrency;
        fastReviewState.tokens = fastReviewState.tokenRate; // Start with 1 second's worth
        fastReviewState.lastTokenUpdate = Date.now();
        if (fastReviewState.pulseTimer) clearInterval(fastReviewState.pulseTimer);
        fastReviewState.pulseTimer = null;
        if (fastReviewState.recoveryTimer) {
            clearInterval(fastReviewState.recoveryTimer);
            fastReviewState.recoveryTimer = null;
        }
        
        log(`⚙️ 快速检阅并发初始化为 ${fastReviewState.concurrency}（上限 ${fastReviewState.maxConcurrency}）`, 'info');
        ensureFastCaptchaWatchdog();
        fastReviewLoop();
    }
    
    function clearFastCaptchaTimers() {
        if (fastReviewState.captchaHeartbeatTimer) {
            clearInterval(fastReviewState.captchaHeartbeatTimer);
            fastReviewState.captchaHeartbeatTimer = null;
        }
        if (fastReviewState.captchaCheckTimer) {
            clearInterval(fastReviewState.captchaCheckTimer);
            fastReviewState.captchaCheckTimer = null;
        }
        if (fastReviewState.manualPopupTimer) {
            clearTimeout(fastReviewState.manualPopupTimer);
            fastReviewState.manualPopupTimer = null;
        }
    }

    function applyFastReviewConcurrencyDrop(reason = 'captcha') {
        const now = Date.now();
        fastReviewState.lastCaptchaAt = now;

        const prev = fastReviewState.concurrency;
        const dropped = Math.max(
            fastReviewState.minConcurrency,
            Math.floor(prev * 0.6) // Drop by 40% instead of 25% for steeper punishment
        );
        fastReviewState.concurrency = dropped;

        if (fastReviewState.recoveryTimer) {
            clearInterval(fastReviewState.recoveryTimer);
            fastReviewState.recoveryTimer = null;
        }

        log(`📉 并发降速(${reason}): ${prev} -> ${dropped}，冷却 ${Math.round(fastReviewState.cooldownMs / 1000)}s`, 'warning');
    }

    function startFastReviewRecoveryRamp() {
        if (fastReviewState.recoveryTimer) {
            clearInterval(fastReviewState.recoveryTimer);
            fastReviewState.recoveryTimer = null;
        }

        fastReviewState.recoveryTimer = setInterval(() => {
            if (!isRunning || currentMode !== 'REVIEW_FAST') {
                clearInterval(fastReviewState.recoveryTimer);
                fastReviewState.recoveryTimer = null;
                return;
            }

            const elapsed = Date.now() - fastReviewState.lastCaptchaAt;
            if (elapsed < fastReviewState.cooldownMs) {
                return;
            }

            const prev = fastReviewState.concurrency;
            if (prev >= fastReviewState.maxConcurrency) {
                clearInterval(fastReviewState.recoveryTimer);
                fastReviewState.recoveryTimer = null;
                return;
            }

            fastReviewState.concurrency = Math.min(
                fastReviewState.maxConcurrency,
                prev + fastReviewState.recoverStep
            );

            log(`📈 并发恢复: ${prev} -> ${fastReviewState.concurrency}`, 'info');

            if (fastReviewState.concurrency >= fastReviewState.maxConcurrency) {
                clearInterval(fastReviewState.recoveryTimer);
                fastReviewState.recoveryTimer = null;
                log(`✅ 并发已恢复到上限 ${fastReviewState.maxConcurrency}`, 'success');
            }
        }, fastReviewState.recoverIntervalMs);
    }

    function releaseCaptchaAndResume(reason, opts = {}) {
        const notifyServer = opts.notifyServer !== false;
        const silent = opts.silent === true;

        if (fastReviewState.recovering) return;
        fastReviewState.recovering = true;

        clearFastCaptchaTimers();
        fastReviewState.captchaMode = false;
        fastReviewState.captchaStartAt = 0;
        fastReviewState.captchaProbeFailCount = 0;

        // 全局锁与旧版锁标记都清理，防止“看起来已过码但系统仍认为在验证”
        GM_setValue('uni_captcha_lock', 0);
        GM_setValue('uni_captcha_worker_active', false);
        GM_setValue('last_captcha_global_time', 0);
        GM_setValue('captcha_solving_tab_id', '');
        GM_deleteValue('uni_captcha_queue');

        if (!silent) {
            log(`✅ 验证码状态已解除: ${reason}`, 'success');
        }

        const done = () => {
            fastReviewState.recovering = false;
            startFastReviewRecoveryRamp();
            if (isRunning && currentMode === 'REVIEW_FAST') {
                refillTaskQueue();
                fastReviewLoop();
            }
        };

        if (!notifyServer) {
            done();
            return;
        }

        fetchApi('/collection/control/resume', {}, () => {
            if (!silent) log('🔄 已通知服务器解除暂停状态', 'success');
            done();
        }, () => {
            if (!silent) log('⚠️ 通知服务器恢复失败，已先恢复前端流水线', 'warning');
            done();
        });
    }

    function ensureFastCaptchaWatchdog() {
        if (fastReviewState.captchaWatchdogTimer) return;

        fastReviewState.captchaWatchdogTimer = setInterval(() => {
            if (!isRunning || currentMode !== 'REVIEW_FAST') {
                return;
            }

            const lockTs = parseInt(GM_getValue('uni_captcha_lock', 0) || 0);
            const lockAge = lockTs ? (Date.now() - lockTs) : 0;

            if (fastReviewState.captchaMode) {
                // 情况1：人工在其他页签过码后，worker已释放锁，但主控探针没感知到
                if (!lockTs) {
                    releaseCaptchaAndResume('检测到全局锁已释放（可能已手动过码）');
                    return;
                }

                // 情况2：锁长期不刷新，疑似死锁
                if (lockAge > 90 * 1000) {
                    releaseCaptchaAndResume(`全局锁超时 ${Math.round(lockAge / 1000)}s，触发自愈恢复`);
                    return;
                }

                // 情况3：验证码模式过长，强制兜底恢复
                if (fastReviewState.captchaStartAt && (Date.now() - fastReviewState.captchaStartAt > 180 * 1000)) {
                    releaseCaptchaAndResume('验证码模式超过180秒，触发兜底恢复');
                }
            } else {
                // 非验证码模式下清理陈旧锁，避免后续误判
                if (lockTs && lockAge > 90 * 1000) {
                    GM_setValue('uni_captcha_lock', 0);
                }
            }
        }, 3000);
    }
    
    // --- Pipeline Logic ---
    
    function fastReviewLoop() {
        // This is now the entry point for the pipeline
        if (!isRunning || currentMode !== 'REVIEW_FAST') return;
        
        // 1. Start the Pulse (Launcher)
        if (!fastReviewState.pulseTimer) {
             fastReviewState.pulseTimer = setInterval(pipelinePulse, 30);
        }
        
        // 2. Start initial fetch
        refillTaskQueue();
    }
    
    // The heartbeat of the pipeline
    function pipelinePulse() {
        if (!isRunning || currentMode !== 'REVIEW_FAST') {
            clearInterval(fastReviewState.pulseTimer);
            fastReviewState.pulseTimer = null;
            return;
        }
        
        if (fastReviewState.captchaMode) return; // Paused for captcha

        // Update UI
        const status = document.getElementById('uni-stats-text');
        if (status) {
            status.innerText = `Pipeline: ${fastReviewState.taskQueue.length} queued | Active: ${fastReviewState.activeCount}/${fastReviewState.concurrency} | ${fastReviewState.stats.success} OK`;
        }

        // Token accumulation
        const now = Date.now();
        const deltaSec = (now - fastReviewState.lastTokenUpdate) / 1000;
        fastReviewState.tokens += deltaSec * fastReviewState.tokenRate;
        // Cap tokens to prevent massive bursts if left idle
        if (fastReviewState.tokens > fastReviewState.tokenRate * 2) { 
            fastReviewState.tokens = fastReviewState.tokenRate * 2;
        }
        fastReviewState.lastTokenUpdate = now;

        // Refill trigger (Aggressive)
        if (fastReviewState.taskQueue.length < 50 && !fastReviewState.fetching) {
            refillTaskQueue();
        }

        // Launch trigger with Token Limit
        while (fastReviewState.activeCount < fastReviewState.concurrency && fastReviewState.taskQueue.length > 0 && fastReviewState.tokens >= 1) {
            fastReviewState.tokens -= 1;
            const task = fastReviewState.taskQueue.shift();
            fastReviewState.activeCount++;
            processItemFast(task);
        }
    }

    function refillTaskQueue() {
        if (fastReviewState.fetching) return;
        fastReviewState.fetching = true;
        
        log("流水线: 补充任务中...", 'info');
        fetchApi('/collection/details/tasks', {}, (res) => {
            fastReviewState.fetching = false;
            if (fastReviewState.captchaMode) return;
            
            const tasks = res.tasks || [];
            if (tasks.length > 0) {
                // Deduplicate? Maybe not needed if backend is good.
                // Just push.
                for (let t of tasks) {
                    fastReviewState.taskQueue.push(t);
                }
                log(`流水线: +${tasks.length} 任务 (池剩余: ${fastReviewState.taskQueue.length})`, 'success');
            } else {
                // Backoff if no tasks
                log("流水线: 无新任务，稍后重试", 'info');
                // Pulse will try again later because queue is low
                // But we should add a small cooldown to avoid spamming /get_tasks
                // Let's set fetching=true for a few seconds? 
                // Better: explicit retry timer.
                fastReviewState.fetching = true; 
                setTimeout(() => { fastReviewState.fetching = false; }, 3000);
            }
        }, (err) => {
            fastReviewState.fetching = false;
            log("补充任务失败", 'error');
            setTimeout(() => { fastReviewState.fetching = false; }, 5000); // Retry delay
        });
    }
    
    function processItemFast(task) {
        fastReviewState.stats.fetched++;
        
        // Step 1: Fetch Detail Page HTML
        // Use sf-item sub-domain often avoids some main-site captchas
        const detailUrl = task.url.includes('sf-item') ? task.url : `https://sf-item.taobao.com/sf_item/${task.id}.htm`;
        
        GM_xmlhttpRequest({
            method: "GET",
            url: detailUrl,
            headers: { "Referer": "https://sf.taobao.com/", "User-Agent": navigator.userAgent },
            onload: function(resp) {
                if (resp.status === 200 && resp.responseText.length > 100) {
                    // Captcha check
                    if (resp.responseText.indexOf('RGV587_ERROR') !== -1) {
                        log(`[${task.id}] 触发验证码!`, 'error');
                        handleFastCaptcha();
                        fastReviewState.activeCount--;
                        return;
                    }
                    
                    // Extract project_id
                    const projectMatch = resp.responseText.match(/project_id=(\d+)/);
                    if (projectMatch) {
                        const projectId = projectMatch[1];
                        // Step 2: Fetch Notice Detail API
                        fetchNoticeDetail(projectId, task.id, (noticeData) => {
                            // Step 3: Build & Submit
                            // Keep extraction server-side: submit raw detail HTML plus notice content.
                            // Reusing logic from taobao_fast_worker: we build HTML combined with notice.
                            const content = buildContent(task.id, detailUrl, resp.responseText, noticeData);
                            submitItemResult(task.id, content);
                        });
                    } else {
                         log(`[${task.id}] 未找到 project_id`, 'warning');
                         handleFastCaptcha(detailUrl);
                         fastReviewState.activeCount--;
                         fastReviewState.stats.failed++;
                    }
                } else {
                    log(`[${task.id}] 页面获取失败: ${resp.status}`, 'error');
                    fastReviewState.activeCount--;
                    fastReviewState.stats.failed++;
                }
            },
            onerror: function() {
                log(`[${task.id}] 网络错误`, 'error');
                fastReviewState.activeCount--;
                fastReviewState.stats.failed++;
            }
        });
    }
    
    function fetchNoticeDetail(projectId, itemId, callback) {
        const url = `https://detail-ext.taobao.com/json/get_project_desc_content.do?project_id=${projectId}&id=${itemId}`;
        GM_xmlhttpRequest({
            method: "GET",
            url: url,
            headers: { "Referer": "https://sf.taobao.com/" },
            onload: function(resp) {
                try {
                    const data = JSON.parse(resp.responseText);
                    callback(data);
                } catch(e) {
                    callback({});
                }
            },
            onerror: () => callback({})
        });
    }
    
    function buildContent(itemId, itemUrl, pageHtml, noticeData) {
    
        // Robust Reconstruct: Do NOT strip scripts/styles blindly as they contain critical data (g_config, etc.)
        let content = pageHtml || '';
        
        // Inject Notice if available
        if (noticeData && noticeData.content) {
             // Try to inject into J_NoticeDetail, or append if not found
             if (content.indexOf('id="J_NoticeDetail"') !== -1) {
                 content = content.replace(
                    /<div[^>]*id="J_NoticeDetail"[^>]*>[\s\S]*?<\/div>/i,
                    `<div id="J_NoticeDetail">${noticeData.content}</div>`
                );
             } else {
                 // Append to body if possible, or just end
                 content += `<div id="J_NoticeDetail" style="display:none">${noticeData.content}</div>`;
             }
        }
        
        // Add Metadata Header
        const header = `<div id="fapaifang-meta" style="display:none">
            <meta name="item_id" content="${itemId}">
            <meta name="original_url" content="${itemUrl}">
        </div>`;
                         
        return header + content;
    }
    
    function submitItemResult(itemId, htmlContent) {
        fetchApi('/collection/details/html', {
            id: itemId,
            html: htmlContent,
            status: 'done'
        }, () => {
             // log(`[${itemId}] 提交成功`, 'success'); // Too spammy for burst mode
             fastReviewState.stats.success++;
             fastReviewState.activeCount--;
        }, () => {
             log(`[${itemId}] 提交失败`, 'error');
             fastReviewState.stats.failed++;
             fastReviewState.activeCount--;
        });
    }
    
    function handleFastCaptcha(targetUrl) {
        log('🚨 handleFastCaptcha 被调用! captchaMode=' + fastReviewState.captchaMode + ' targetUrl=' + (targetUrl || 'default'), 'error');
        
        if (fastReviewState.captchaMode) {
            log('⏭️ captchaMode 已激活，跳过重复触发（等待上一轮解决）', 'warning');
            return;
        }
        fastReviewState.captchaMode = true;
        fastReviewState.captchaStartAt = Date.now();
        fastReviewState.captchaProbeFailCount = 0;
        applyFastReviewConcurrencyDrop('captcha');
        ensureFastCaptchaWatchdog();
        log('🔒 检测到验证码/异常，暂停请求流水线...', 'warning');

        // REPORT TO SERVER (Heartbeat)
        clearFastCaptchaTimers();
        fastReviewState.captchaHeartbeatTimer = setInterval(() => {
            if (!fastReviewState.captchaMode) return;
            fetchApi('/report_captcha', {}, (res) => {
                 if (res.status === 'solving') {
                     log('🤖 服务器正在解决验证码...', 'info');
                 }
            });
        }, 5000);
        // Fire first one immediately
        fetchApi('/report_captcha', {});

        // Push task to Worker Queue IMMEDIATELY (no random delay!)
        const now = Date.now();
        const lastLock = GM_getValue('uni_captcha_lock', 0);
        const lockAge = now - lastLock;
        log(`🔍 全局锁检查: lockAge=${lockAge}ms (阈值: 30000ms)`, 'info');
        
        if (lockAge < 30 * 1000) {
            log('🔒 全局锁生效中 (另一个工人在处理)，本次不推送新任务', 'info');
        } else {
            log('🔒 [Winner] 获取全局锁！推送验证码任务到打工窗口...', 'error');
            GM_setValue('uni_captcha_lock', now);
            
            const urlToOpen = targetUrl || 'https://sf-item.taobao.com/sf_item/1015214534677.htm';
            const sep = urlToOpen.includes('?') ? '&' : '?';
            const bgUrl = urlToOpen + sep + '__captcha_solver_bg=1';
            
            const task = { url: bgUrl, timestamp: now };
            GM_setValue('uni_captcha_queue', task);
            log('✅ 任务已推送到后台队列 uni_captcha_queue', 'success');
            
            // --- FAILSAFE / FALLBACK 单实例弹窗方案 ---
            // 不再立即弹窗：先给打工页机会处理，避免积累大量未处理弹窗
            if (fastReviewState.manualPopupTimer) {
                clearTimeout(fastReviewState.manualPopupTimer);
                fastReviewState.manualPopupTimer = null;
            }

            fastReviewState.manualPopupTimer = setTimeout(() => {
                if (!fastReviewState.captchaMode) return;

                // 若队列已被打工页消费，说明它在处理，不再弹人工窗
                const pendingTask = GM_getValue('uni_captcha_queue', null);
                if (!pendingTask || !pendingTask.url) {
                    log('✅ 打工页已接手验证码任务，跳过人工弹窗', 'info');
                    return;
                }

                // 全局节流：同一时段只允许一个人工验证码弹窗
                const nowTs = Date.now();
                const lastPopupOpen = parseInt(GM_getValue('uni_captcha_popup_last_open', 0) || 0);
                const popupCooldownMs = 180 * 1000; // 3分钟内不重复弹
                if (nowTs - lastPopupOpen < popupCooldownMs) {
                    log('⏭️ 人工验证码弹窗冷却中，跳过重复弹窗', 'warning');
                    return;
                }

                const sep2 = urlToOpen.includes('?') ? '&' : '?';
                const manualUrl = urlToOpen + sep2 + '__captcha_manual_popup=1';
                GM_setValue('uni_captcha_popup_last_open', nowTs);
                window.open(manualUrl, '_blank', 'width=900,height=700,left=100,top=100');
                log('⚠️ 打工页未接手，已打开单实例人工验证码弹窗', 'warning');
            }, 15000); // 15s 后才兜底

            log('✅ 任务已推送: ' + bgUrl, 'success');
        }
        
        // Poll to check if captcha is cleared
        fastReviewState.captchaCheckTimer = setInterval(() => {
            if (!isRunning || currentMode !== 'REVIEW_FAST' || !fastReviewState.captchaMode) {
                log('🛑 探针检测到终止信号或收到解除指令，退出循环。', 'info');
                clearFastCaptchaTimers();
                return;
            }
            
            const elapsed = Math.round((Date.now() - fastReviewState.captchaStartAt) / 1000);
            log(`🔄 验证码探针检测中... (${elapsed}s)`, 'info');
            
            GM_xmlhttpRequest({
                method: "GET",
                url: 'https://sf-item.taobao.com/sf_item/1.htm',
                onload: (r) => {
                    if (!fastReviewState.captchaMode) return;

                    if (r.responseText.indexOf('RGV587_ERROR') === -1) {
                        releaseCaptchaAndResume('探针确认验证码已解除');
                    } else {
                        // Keep lock alive
                        if (Date.now() - GM_getValue('uni_captcha_lock', 0) > 30000) {
                            GM_setValue('uni_captcha_lock', Date.now());
                        }
                    }
                },
                onerror: () => {
                    fastReviewState.captchaProbeFailCount++;
                    log(`⚠️ 探针请求失败（网络错误，第${fastReviewState.captchaProbeFailCount}次）`, 'warning');
                    // 连续失败时，交给看门狗根据锁状态兜底恢复
                }
            });
        }, 5000); // Check every 5s
    }

    // ==========================================
    // MODULE 3: SLOW REVIEW (Master Page - Tab Manager)
    // ==========================================
    let slowReviewState = { 
        maxSlots: 10, 
        slots: [], 
        interval: 2000,
        running: false
    };

    function startSlowReview() {
         log('启动慢速检阅 (Tab) 逻辑...', 'info');
         slowReviewState.running = true;
         slowReviewLoop();
    }
    
    function slowReviewLoop() {
        if (!isRunning || currentMode !== 'REVIEW_SLOW') {
            slowReviewState.running = false;
            return;
        }

        // Global Lock Check
        const lastLock = GM_getValue('uni_captcha_lock', 0);
        if (Date.now() - lastLock < 60 * 1000) {
            const status = document.getElementById('uni-stats-text');
            if (status) status.innerText = `⚠️ 暂停中: 等待验证码解决...`;
            setTimeout(slowReviewLoop, 3000); // Check again later
            return;
        }
        
        // Clean up closed slots
        slowReviewState.slots = slowReviewState.slots.filter(s => !s.closed);

        const status = document.getElementById('uni-stats-text');
        if (status) status.innerText = `Tabs: ${slowReviewState.slots.length}/${slowReviewState.maxSlots}`;

        if (slowReviewState.slots.length < slowReviewState.maxSlots) {
             fetchApi('/collection/details/tasks', {}, (res) => {
                 if (res.tasks && res.tasks.length > 0) {
                     const task = res.tasks[0]; // Take one
                     log(`打开任务: ${task.id}`, 'info');
                     
                     // Use auto_worker=1 param to trigger worker mode
                     const url = task.url + (task.url.includes('?') ? '&' : '?') + 'auto_worker=1';
                     const win = GM_openInTab(url, { active: false, insert: true });
                     
                     slowReviewState.slots.push(win);
                 } else {
                     log("无待处理任务...", 'info');
                 }
                 setTimeout(slowReviewLoop, slowReviewState.interval);
             }, () => {
                 setTimeout(slowReviewLoop, slowReviewState.interval);
             });
        } else {
             setTimeout(slowReviewLoop, 1000);
        }
    }

    // --- Optimization: Event-Driven Concurrency ---
    // Listen for worker completion signals to trigger immediate loop check
    if (typeof GM_addValueChangeListener !== 'undefined') {
        let debounceTimer = null;
        GM_addValueChangeListener('uni_signal_slot_free', function(name, oldVal, newVal, remote) {
            if (remote) {
                // Debounce to avoid flooding
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    if (isRunning && currentMode === 'REVIEW_SLOW') {
                         log('♻️ 收到Worker空闲信号，立即填充...', 'info');
                         slowReviewLoop();
                    }
                }, 200);
            }
        });

        // 关键恢复链路：当任何页面释放全局验证码锁时，主控立即恢复流水线
        GM_addValueChangeListener('uni_captcha_lock', function(name, oldVal, newVal, remote) {
            if (!remote) return;
            if (currentMode === 'REVIEW_FAST' && isRunning && fastReviewState.captchaMode && (!newVal || parseInt(newVal) === 0)) {
                releaseCaptchaAndResume('收到全局锁释放信号（跨页签）');
            }
        });
    }

    function handleSlowCaptcha() {
         log('🔒 [Worker] 检测到验证码/异常，尝试设置全局锁...', 'warning');
         // Global Lock Check
         const now = Date.now();
         const lastLock = GM_getValue('uni_captcha_lock', 0);
         
         // Only set lock if not already locked by someone else recently (or if we are the ones who locked it?)
         // For simplicity: if lock is old (>60s) OR we are just detecting it now, we take over.
         GM_setValue('uni_captcha_lock', now);
         logToMaster('🔒 [Worker] 已设置全局锁，开启心跳保活...', 'error');
         
         const workerStartTime = Date.now();
         
         // HEARTBEAT LOOP: Keep lock alive while captcha exists
         const heartbeat = setInterval(() => {
             // Check if Master forcibly unlocked the system
             const forceUnlockTime = GM_getValue('uni_captcha_force_unlock', 0);
             if (forceUnlockTime > workerStartTime) {
                 clearInterval(heartbeat);
                 GM_setValue('uni_captcha_lock', 0);
                 logToMaster('🛑 [Worker] 接收到强制解锁指令，中止验证循环 (3秒后自动关闭此工作页)', 'warning');
                 // If the master force unlocked, we should kill this tab so it stops disrupting the flow
                 setTimeout(() => window.close(), 3000);
                 return;
             }
         
             // Check if captcha elements still exist
             const hasCaptcha = hasCaptchaChallenge(document);
             
             if (hasCaptcha) {
                 // Refresh lock to prevent expiry
                 GM_setValue('uni_captcha_lock', Date.now());
                 logToMaster('🔒 [Worker] 验证码未解除，刷新全局锁...', 'warning');
             } else {
                 // Captcha gone! Release lock and reload
                 clearInterval(heartbeat);
                 GM_setValue('uni_captcha_lock', 0);
                 logToMaster('✅ [Worker] 验证码已解除，释放锁并刷新...', 'success');
                 window.location.reload();
             }
         }, 5000); // Check every 5s
    }
    // ==========================================
    // MODULE 4: WORKER (Detail Page - Automatic)
    // ==========================================
    function initWorker() {
        if (!isDetail) return;
        if (autoWorkerMode === '1') {
            log('自动工作模式已激活', 'success');
            
            // Wait for Helper to load or just scrape directly?
            // To reuse Helper logic, we can inspect DOM
            setTimeout(() => {
                const helperBtn = document.getElementById('helper-start-btn'); // Assuming Helper UI exists
                if (helperBtn) {
                     // If Helper is unified, we might just call internal function
                     // But Helper might be same file. 
                     // Let's scrape directly for reliability.
                     doWorkerScrape();
                } else {
                     doWorkerScrape();
                }
            }, 3000);
        } else {
            // Check for Captcha immediately
            if (hasCaptchaChallenge(document)) {
                handleSlowCaptcha();
            }
        }
    }
    
    function pruneDOM() {
        logToMaster("Pruning DOM for memory optimization...", 'info');
        
        // 1. Remove specific heavy/useless areas first (Headers, Footers, Sidebars)
        const selectorRemovals = [
            '.tb-footer', '#J_SiteFooter', '#sf-foot-2014', '.sf-foot-2014',
            '.pm-main-l', '#J_UlThumb', '.J_HeadImageWrap',
            '#J_SiteNav', '.site-nav', '#sf-head-2014', '.sf-head-2014', '.nav-con',
            '.search-bar', '#J_Search', '.top-nav-bar'
        ];
        selectorRemovals.forEach(sel => {
             document.querySelectorAll(sel).forEach(el => el.remove());
        });

        // 2. Remove Media & Scripts & Interactive Elements
        const tagsToRemove = ['script', 'style', 'link', 'svg', 'iframe', 'noscript', 'meta', 'img', 'video', 'canvas', 'input', 'button', 'select', 'textarea'];
        tagsToRemove.forEach(tag => {
            const elements = document.querySelectorAll(tag);
            elements.forEach(el => el.remove());
        });

        // 3. Remove Comments
        const removeComments = (node) => {
            if (!node) return;
            for (let i = node.childNodes.length - 1; i >= 0; i--) {
                const child = node.childNodes[i];
                if (child.nodeType === 8) { // Comment
                    node.removeChild(child);
                } else if (child.nodeType === 1) { // Element
                    removeComments(child);
                }
            }
        };
        try { removeComments(document.body); } catch(e) {}

        // 4. Remove Attributes (except ID) - AGGRESSIVE
        // This makes the HTML much smaller for the LLM
        const all = document.getElementsByTagName("*");
        for (let i = 0, max = all.length; i < max; i++) {
             const el = all[i];
             const attrs = Array.from(el.attributes || []);
             for (const attr of attrs) {
                 const name = attr.name.toLowerCase();
                 // Keep ID for structure, Keep row/colspan for tables
                 if (name !== 'id' && name !== 'rowspan' && name !== 'colspan') {
                     el.removeAttribute(attr.name);
                 }
             }
        }
        
        logToMaster("DOM Pruned.", 'success');
    }

    function doWorkerScrape() {
        // Simple extraction for Worker
        
        // Optimize BEFORE grabbing HTML
        pruneDOM();

        const html = document.documentElement.outerHTML;
        const itemIdMatch = window.location.href.match(/id=(\d+)/) || window.location.pathname.match(/\/(\d+)\.htm/);
        const itemId = itemIdMatch ? itemIdMatch[1] : 'unknown';
        
        logToMaster(`抓取内容 (ID: ${itemId}), HTML大小: ${Math.round(html.length/1024)}KB...`, 'info');
        
        fetchApi('/analyze_html', {
            id: itemId,
            html: html,
            status: 'done'
        }, () => {
             logToMaster(`[ID:${itemId}] 上传成功，准备关闭...`, 'success');
             setTimeout(() => window.close(), 1000);
        }, () => {
             logToMaster(`[ID:${itemId}] 上传失败!`, 'error');
             setTimeout(() => window.close(), 5000);
        });

        // Trigger Slot Free Signal just before closing
        GM_setValue('uni_signal_slot_free', Date.now());
    }

    function getCleanDetailContext() {
        let parts = [];
        const notice = document.querySelector('#J_NoticeDetail');
        if (notice && notice.innerText.trim().length > 10) parts.push('【公告详情】\n' + notice.innerText.trim());

        const desc = document.querySelector('#J_desc');
        if (desc && desc.innerText.trim().length > 10) parts.push('【标的物描述】\n' + desc.innerText.trim());

        const main = document.querySelector('.pm-main');
        if (main && main.innerText.trim().length > 10) parts.push('【拍卖主信息】\n' + main.innerText.trim());

        if (parts.length === 0) parts.push(document.body.innerText.replace(/\n{3,}/g, '\n\n').trim());

        return parts.join('\n---\n').substring(0, 3000);
    }

    function extractDetailPageData() {
        const url = window.location.href;
        const itemIdMatch = url.match(/[?&]id=(\d+)/) || url.match(/\/(\d+)\.htm/) || url.match(/\/(\d+)(?:\?|$)/);
        const id = itemIdMatch ? itemIdMatch[1] : 'unknown';

        let title = '';
        const h1 = document.querySelector('.pm-main > h1') || document.querySelector('h1');
        if (h1) title = h1.innerText.replace(/\s+/g, ' ').trim();
        else title = document.title.trim();

        const pageText = document.body.innerText;

        let data = {
            id: id,
            title: title,
            标题: title,
            context: getCleanDetailContext(),
            原始网站: url,
            is_processed: true,
            '是否成交': false,
            '成交价格': 0,
            '市场评估价': 0,
            '起拍价格': 0,
            '保证金': 0,
            '竞拍人数': 0,
            '出价次数': 0,
            '出价人数': 0,
            '围观人数': 0,
            '提醒人数': 0,
            '浏览次数': 0,
            '建筑面积': 0,
            '产权建筑面积': 0,
            '产权份额比例': 1,
            '完整地址': '',
            '法院名称': '',
            '案号': ''
        };

        // Strategy 1: Parse J_COMPONENT script tags
        try {
            const componentScripts = document.querySelectorAll('script.J_COMPONENT');
            for (const script of componentScripts) {
                try {
                    const raw = script.textContent.trim();
                    if (!raw) continue;
                    const decoded = decodeURIComponent(raw);
                    const json = JSON.parse(decoded);

                    if (json.key === 'STATISTICS_INFO' && json.dataSource) {
                        const ds = json.dataSource;
                        if (ds.applyNumber !== undefined && ds.applyNumber >= 0) data['竞拍人数'] = parseInt(ds.applyNumber) || 0;
                        if (ds.bidUserNumber !== undefined && ds.bidUserNumber >= 0) data['出价人数'] = parseInt(ds.bidUserNumber) || 0;
                        if (ds.bidCount !== undefined && ds.bidCount >= 0) data['出价次数'] = parseInt(ds.bidCount) || 0;
                        if (ds.watchCount !== undefined && ds.watchCount >= 0) data['围观人数'] = parseInt(ds.watchCount) || 0;
                        if (ds.remindCount !== undefined && ds.remindCount >= 0) data['提醒人数'] = parseInt(ds.remindCount) || 0;
                        if (ds.viewCount !== undefined && ds.viewCount >= 0) data['浏览次数'] = parseInt(ds.viewCount) || 0;
                    }

                    if (json.key === 'AUCTION_RULE' && json.dataSource && json.dataSource.bidRuleFields) {
                        for (const field of json.dataSource.bidRuleFields) {
                            if (!field.title || !field.texts || !field.texts.length) continue;
                            const val = field.texts[0].preMsg;
                            if (!val) continue;
                            const numVal = parseFloat(val.replace(/[^\d.]/g, '')) || 0;
                            if (field.title.includes('评估价') || field.title.includes('市场价')) {
                                data['市场评估价'] = numVal;
                            } else if (field.title.includes('起拍价')) {
                                data['起拍价格'] = numVal;
                            } else if (field.title.includes('保证金')) {
                                data['保证金'] = numVal;
                            }
                        }
                    }

                    if (json.key === 'BID_CONTROL' && json.dataSource) {
                        const ds = json.dataSource;
                        if (ds.startTime) {
                            const startDate = new Date(ds.startTime);
                            data['开拍时间'] = formatLocalDateTime(startDate);
                        }
                        if (ds.endTime) {
                            const endDate = new Date(ds.endTime);
                            data['交易时间'] = formatLocalDateTime(endDate);
                        }
                        if (ds.currentPrice) {
                            data['成交价格'] = parseFloat(ds.currentPrice) || 0;
                        }
                        if (ds.bidCount !== undefined && ds.bidCount >= 0) {
                            data['出价次数'] = parseInt(ds.bidCount) || 0;
                        }
                        if (ds.bidUserNumber !== undefined && ds.bidUserNumber >= 0) {
                            data['出价人数'] = parseInt(ds.bidUserNumber) || 0;
                        }
                        if (ds.status === 'done' || ds.status === 'succ') {
                            data['是否成交'] = true;
                        }
                    }

                    if ((json.key === 'ITEM_INFO' || json.key === 'HEADER') && json.dataSource) {
                        const ds = json.dataSource;
                        if (ds.title && !data['标题']) data['标题'] = ds.title;
                    }

                } catch (e) { /* ignore */ }
            }
        } catch (e) { console.warn('[DetailHelper] J_COMPONENT error:', e); }

        // Strategy 2: Text/DOM-based fallbacks
        if (!data['成交价格'] || data['成交价格'] === 0) {
            const priceEl = document.querySelector('.pm-current-price .pm-price') || document.querySelector('.current-price .price') || document.querySelector('.sf-price');
            if (priceEl) data['成交价格'] = parseFloat(priceEl.textContent.replace(/[^\d.]/g, '')) || 0;

            if (!data['成交价格']) {
                const dealMatch = pageText.match(/(?:当前价|成交价|拍卖价|竞价结果)[：:\s]*[¥￥]?([\d,]+(?:\.\d+)?)/);
                if (dealMatch) data['成交价格'] = parseFloat(dealMatch[1].replace(/,/g, ''));
            }
        }

        if (!data['竞拍人数']) {
            const statEls = document.querySelectorAll('.sf-stats span, .pm-bid-info span, .bid-info span, .J_Stats span');
            for (const el of statEls) {
                const m = el.textContent.match(/(\d+)\s*人报名/);
                if (m) { data['竞拍人数'] = parseInt(m[1]); break; }
            }
        }
        if (!data['出价次数']) {
            const bidCountMatch = pageText.match(/(?:出价次数|竞价次数)[：:\s]*(\d+)/);
            if (bidCountMatch) data['出价次数'] = parseInt(bidCountMatch[1]) || 0;
        }
        if (!data['出价人数']) {
            const bidderMatch = pageText.match(/(?:出价人数|竞买记录中共有|共有)\s*(\d+)\s*(?:人出价|位出价人|人参与出价)/);
            if (bidderMatch) data['出价人数'] = parseInt(bidderMatch[1]) || 0;
        }

        if (!data['是否成交'] && (pageText.includes('已成交') || pageText.includes('竞价成功'))) {
            data['是否成交'] = true;
        }

        if (!data['地点']) {
            const addressMatch = pageText.match(/标的物(?:所在)?位置[：:\s]*([\S\s]+?)[\r\n]/) || pageText.match(/坐落(?:于)?[：:\s]*([\S\s]+?)[\r\n]/);
            if (addressMatch) data['地点'] = addressMatch[1].trim();
        }
        if (data['地点'] && !data['完整地址']) data['完整地址'] = data['地点'];

        if (!data['法院名称']) {
            const courtMatch = pageText.match(/([\u4e00-\u9fa5]{2,30}人民法院)/);
            if (courtMatch) data['法院名称'] = courtMatch[1];
        }
        if (!data['案号']) {
            const caseMatch = pageText.match(/[（(]\d{4}[)）][^\s，。,；;:：]{2,40}号/);
            if (caseMatch) data['案号'] = caseMatch[0];
        }

        // Parse Address Components
        if (data['完整地址'] || data['地点']) {
            const addr = data['完整地址'] || data['地点'];
            const provMatch = addr.match(/(.+?省)/);
            if (provMatch) data['省份'] = provMatch[1];

            const cityMatch = addr.match(/(.+?市)/);
            if (cityMatch) {
                let city = cityMatch[1];
                if (data['省份']) city = city.replace(data['省份'], '');
                data['城市'] = city;
            }

            const distMatch = addr.match(/(.+?[区县])/);
            if (distMatch) {
                let dist = distMatch[1];
                if (data['省份']) dist = dist.replace(data['省份'], '');
                if (data['城市']) dist = dist.replace(data['城市'], '');
                data['区'] = dist;
            }

            const commMatch = addr.match(/([^\s省市区县]+?(?:小区|花园|苑|大厦|公寓|别墅|山庄))/);
            if (commMatch) data['所属小区'] = commMatch[1];
        }

        // Area Extraction
        if (!data['建筑面积']) {
            const areaPatterns = [
                /(?<!套内)建筑面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)\s*(?:平方米|平米|㎡|m²)?/i,
                /房屋建筑面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)/i,
                /房屋面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)/i,
                /产权面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)/i,
                /总面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)/i,
                /(\d+(?:\.\d+)?)\s*(?:㎡|m²)/i
            ];
            for (const p of areaPatterns) {
                const m = pageText.match(p);
                if (m) {
                    data['建筑面积'] = parseFloat(m[1].replace(',', '.'));
                    break;
                }
            }
        }
        if (!data['产权建筑面积'] && data['建筑面积']) data['产权建筑面积'] = data['建筑面积'];

        const ratioPatterns = [
            /(\d+)\s*\/\s*(\d+)\s*(?:产权|份额)/,
            /(\d+(?:\.\d+)?)\s*%\s*(?:产权|份额)/,
            /二分之一产权/,
            /三分之一产权/,
            /四分之一产权/
        ];
        for (const pattern of ratioPatterns) {
            const match = pageText.match(pattern);
            if (!match) continue;
            if (pattern === ratioPatterns[2]) data['产权份额比例'] = 0.5;
            else if (pattern === ratioPatterns[3]) data['产权份额比例'] = 1 / 3;
            else if (pattern === ratioPatterns[4]) data['产权份额比例'] = 0.25;
            else if (match.length >= 3) data['产权份额比例'] = (parseFloat(match[1]) || 0) / (parseFloat(match[2]) || 1);
            else data['产权份额比例'] = (parseFloat(match[1]) || 0) / 100;
            break;
        }

        return data;
    }

    // ==========================================
    // MODULE 5: HELPER (Detail Page - Manual UI)
    // ==========================================
    function initHelper() {
        if (!isDetail) return;
        // Avoid double loading
        if (document.getElementById('detail-helper-panel')) return;

        log('加载详情助手 UI (完整版)...', 'info');
        
        // --- Helper Config & State ---
        const IS_AUTO_MODE = new URLSearchParams(window.location.search).get('auto_fix') === '1';
        let isPanelMinimized = GM_getValue('dh_panel_minimized', false);

        // Data Fields Config
        const FIELDS = [
            { key: 'id', label: 'ID', type: 'number', readonly: true },
            { key: '市场评估价', label: '市场评估价', type: 'number' },
            { key: '起拍价格', label: '起拍价格', type: 'number' },
            { key: '成交价格', label: '成交价格', type: 'number' },
            { key: '保证金', label: '保证金', type: 'number' },
            { key: '交易时间', label: '交易时间', type: 'text' }, // yyyy/MM/dd HH:mm:ss
            { key: '开拍时间', label: '开拍时间', type: 'text' },
            { key: '原始网站', label: '原始网站', type: 'text', readonly: true },
            { key: '是否成交', label: '是否成交', type: 'checkbox' },
            { key: '竞拍人数', label: '竞拍人数', type: 'number' },
            { key: '出价次数', label: '出价次数', type: 'number' },
            { key: '出价人数', label: '出价人数', type: 'number' },
            { key: '围观人数', label: '围观人数', type: 'number' },
            { key: '提醒人数', label: '提醒人数', type: 'number' },
            { key: '浏览次数', label: '浏览次数', type: 'number' },
            { key: '地点', label: '地点', type: 'text' },
            { key: '完整地址', label: '完整地址', type: 'text' },
            { key: '所属小区', label: '所属小区', type: 'text' },
            { key: '省份', label: '省份', type: 'text' },
            { key: '城市', label: '城市', type: 'text' },
            { key: '区', label: '区', type: 'text' },
            { key: '最靠近商圈', label: '最靠近商圈', type: 'text' },
            { key: '建筑面积', label: '建筑面积', type: 'number', step: 0.01 },
            { key: '产权建筑面积', label: '产权建筑面积', type: 'number', step: 0.01 },
            { key: '产权份额比例', label: '产权份额比例', type: 'number', step: 0.0001 },
            { key: '法院名称', label: '法院名称', type: 'text' },
            { key: '案号', label: '案号', type: 'text' },
            { key: '单价', label: '单价', type: 'number', readonly: true }, // Auto-calculated
        ];

        // --- Core Logic Helpers ---

        // --- Data Loading ---
        async function loadDataWithPriority(forcePage = false) {
            updateStatus('正在加载数据...');
            
            // 1. Local Backend (Highest)
            const itemIdMatch = window.location.href.match(/[?&]id=(\d+)/) || window.location.pathname.match(/\/(\d+)\.htm/);
            const id = itemIdMatch ? itemIdMatch[1] : null;
            
            if (id) {
                try {
                    const response = await new Promise(resolve => {
                         fetchApi(`/get_item?id=${id}`, {}, resolve, () => resolve({error: true}));
                    });
                    if (response && !response.error && Object.keys(response).length > 0) {
                        log('Loaded Local Data', 'success');
                        updateStatus('✅ 已加载本地存档数据 (独占模式)');
                        return response;
                    }
                } catch(e) {}
            }
            
            // 2. URL Params (Middle)
            const urlParams = new URLSearchParams(window.location.search);
            let urlData = {};
            let hasUrlData = false;
            FIELDS.forEach(field => {
                const paramVal = urlParams.get(field.key);
                if (paramVal !== null && paramVal !== undefined && paramVal !== '') {
                     hasUrlData = true;
                     if (field.type === 'number') urlData[field.key] = parseFloat(paramVal);
                     else if (field.type === 'checkbox') urlData[field.key] = (paramVal === 'true' || paramVal === '1');
                     else urlData[field.key] = decodeURIComponent(paramVal);
                }
            });
            if (hasUrlData) {
                if (!urlData['id']) urlData['id'] = id || 'unknown';
                updateStatus('⚠️ 使用URL传入数据 (独占模式)');
                return urlData;
            }
            
            // 3. Page Extraction (Lowest)
            updateStatus('⚠️ 使用页面抓取数据');
            return extractDetailPageData();
        }

        // --- UI Construction ---
        function createPanel() {
            let panel = document.getElementById('detail-helper-panel');
            if (!panel) {
                panel = document.createElement('div');
                panel.id = 'detail-helper-panel';
                document.body.appendChild(panel);
            }
            updatePanelStyle();
        }

        function updatePanelStyle() {
            const panel = document.getElementById('detail-helper-panel');
            if (!panel) return;

            if (isPanelMinimized) {
                panel.innerHTML = `
                    <div style="padding: 8px 12px; background: #f5f5f5; display: flex; justify-content: space-between; align-items: center;">
                        <b style="font-size: 14px;">📝 助手</b>
                        <div>
                            <button id="dh-bar-refresh" style="border:none; background:none; cursor:pointer;" title="同步">🔄</button>
                            <button id="dh-bar-expand" style="border:none; background:none; cursor:pointer;" title="展开">🔼</button>
                        </div>
                    </div>`;
                Object.assign(panel.style, {
                    position: 'fixed', top: '100px', right: '20px', width: '200px', height: 'auto',
                    background: 'white', border: '1px solid #ccc', zIndex: '999990',
                    borderRadius: '8px', boxShadow: '0 0 10px rgba(0,0,0,0.1)'
                });
                document.getElementById('dh-bar-expand').onclick = togglePanel;
                document.getElementById('dh-bar-refresh').onclick = () => refreshData();
            } else {
                Object.assign(panel.style, {
                    position: 'fixed', top: '100px', right: '20px', width: '320px', maxHeight: '80vh',
                    background: 'white', border: '1px solid #ccc', zIndex: '999990', overflowY: 'auto',
                    borderRadius: '8px', boxShadow: '0 0 20px rgba(0,0,0,0.2)'
                });
                renderPanelContent(panel);
                refreshData();
            }
        }

        function togglePanel() {
            isPanelMinimized = !isPanelMinimized;
            GM_setValue('dh_panel_minimized', isPanelMinimized);
            updatePanelStyle();
        }

        function renderPanelContent(panel) {
            panel.innerHTML = `
                <div style="padding: 12px; background: #f5f5f5; border-bottom: 1px solid #ddd; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 10;">
                    <b style="font-size: 14px;">📝 数据录入助手</b>
                    <div>
                         <button id="dh-btn-refresh" style="border:none; background:none; cursor:pointer; font-size:16px;" title="刷新">🔄</button>
                         <button id="dh-btn-min" style="border:none; background:none; cursor:pointer; font-size:16px;" title="最小化">➖</button>
                    </div>
                </div>
                <div id="dh-form-container" style="padding: 15px;"></div>
                <div style="padding: 12px; background: #f5f5f5; border-top: 1px solid #ddd; position: sticky; bottom: 0; text-align: center;">
                    <div id="dh-status" style="margin-bottom: 8px; font-size: 12px; color: #666; height: 1.5em;"></div>
                    <div style="display: flex; gap: 8px;">
                        <button id="dh-btn-infer" style="flex: 1; padding: 10px; background: #9c27b0; color: white; border: none; border-radius: 4px; cursor: pointer;">🔍 推断位置</button>
                        <button id="dh-btn-submit" style="flex: 2; padding: 10px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">提交保存</button>
                    </div>
                </div>`;

            const container = panel.querySelector('#dh-form-container');
            FIELDS.forEach(field => {
                const row = document.createElement('div');
                row.style.marginBottom = '10px';
                const label = document.createElement('label');
                label.textContent = field.label;
                label.style.display = 'block';
                label.style.marginBottom = '4px';
                label.style.color = '#666';

                let input = document.createElement('input');
                if (field.type === 'checkbox') {
                    input.type = 'checkbox';
                    label.style.display = 'inline-block';
                    input.style.marginLeft = '8px';
                    row.appendChild(label);
                    row.appendChild(input);
                } else {
                    input.type = field.type;
                    input.style.width = '100%';
                    input.style.padding = '6px';
                    input.style.border = '1px solid #ccc';
                    input.style.borderRadius = '4px';
                    if (field.readonly) { input.readOnly = true; input.style.background = '#eee'; }
                    if (field.step) input.step = field.step;
                    row.appendChild(label);
                    row.appendChild(input);
                }
                input.id = `dh-input-${field.key}`;
                if (['建筑面积', '成交价格', '起拍价格'].includes(field.key)) {
                    input.addEventListener('input', calculateUnitPrice);
                }
                container.appendChild(row);
            });

            document.getElementById('dh-btn-min').onclick = togglePanel;
            document.getElementById('dh-btn-refresh').onclick = () => refreshData();
            document.getElementById('dh-btn-submit').onclick = submitData;
            document.getElementById('dh-btn-infer').onclick = inferLocation;
        }

        // --- Actions ---
        
        async function refreshData() {
            const data = await loadDataWithPriority();
            FIELDS.forEach(field => {
                const input = document.getElementById(`dh-input-${field.key}`);
                if (input) {
                    if (field.type === 'checkbox') input.checked = !!data[field.key];
                    else input.value = (data[field.key] !== undefined && data[field.key] !== null) ? data[field.key] : '';
                }
            });
            calculateUnitPrice();
            
            if (IS_AUTO_MODE) {
                const areaInput = document.getElementById('dh-input-建筑面积');
                if (areaInput && (!parseFloat(areaInput.value) || parseFloat(areaInput.value) === 0)) {
                    scrollAndRetryArea();
                } else {
                    checkAutoSubmit();
                }
            }
        }
        
        function calculateUnitPrice() {
             const area = parseFloat(document.getElementById('dh-input-建筑面积')?.value) || 0;
             let price = parseFloat(document.getElementById('dh-input-成交价格')?.value) || 0;
             if (price <= 0) price = parseFloat(document.getElementById('dh-input-起拍价格')?.value) || 0;
             
             const unitInput = document.getElementById('dh-input-单价');
             if (unitInput) {
                 unitInput.value = (area > 0 && price > 0) ? (price / area).toFixed(2) : 0;
             }
        }
        
        function scrollAndRetryArea() {
            updateStatus('⏳ 滚动加载详情中...');
            window.scrollTo({ top: document.body.scrollHeight * 0.75, behavior: 'smooth' });
            setTimeout(() => {
                const pageText = document.body.innerText;
                const areaPatterns = [
                    /(?<!套内)建筑面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)\s*(?:平方米|平米|㎡|m²)?/i,
                    /房屋建筑面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)/i,
                ];
                let foundArea = 0;
                for (const p of areaPatterns) {
                    const m = pageText.match(p);
                    if (m) { foundArea = parseFloat(m[1].replace(',', '.')); break; }
                }
                
                if (foundArea > 0) {
                    const el = document.getElementById('dh-input-建筑面积');
                    if(el) el.value = foundArea;
                    calculateUnitPrice();
                    updateStatus('✅ 建筑面积已补充提取');
                } else {
                    updateStatus('⚠️ 面积未找到，继续提交');
                }
                window.scrollTo({ top: 0, behavior: 'smooth' });
                checkAutoSubmit();
            }, 3000);
        }
        
        function inferLocation(callback) {
            const address = document.getElementById('dh-input-完整地址')?.value.trim() || document.getElementById('dh-input-地点')?.value.trim();
            if (!address) { updateStatus('⚠️ 需要地址', '#ff9800'); return; }
            
            updateStatus('🔍 AI推断位置中...', '#9c27b0');
            const btn = document.getElementById('dh-btn-infer');
            if(btn) btn.disabled = true;

            fetchApi('/infer_location', { address: address, title: document.title }, (result) => {
                if(btn) btn.disabled = false;
                let updated = [];
                if (result['所属小区']) {
                     const el = document.getElementById('dh-input-所属小区');
                     if(el) { el.value = result['所属小区']; updated.push('小区: '+result['所属小区']); }
                }
                if (result['最靠近商圈']) {
                     const el = document.getElementById('dh-input-最靠近商圈');
                     if(el) { el.value = result['最靠近商圈']; updated.push('商圈: '+result['最靠近商圈']); }
                }
                updateStatus(updated.length ? '✅ '+updated.join(', ') : '⚠️ AI未推断出信息', updated.length ? '#4caf50':'#ff9800');
                if (typeof callback === 'function') callback(true);
            }, () => {
                if(btn) btn.disabled = false;
                updateStatus('❌ 推断失败', '#f44336');
                if (typeof callback === 'function') callback(false);
            });
        }
        
        function collectFormData() {
            let data = {};
            const url = window.location.href;
            const itemIdMatch = url.match(/[?&]id=(\d+)/) || url.match(/\/(\d+)\.htm/);
            data.id = itemIdMatch ? itemIdMatch[1] : 'unknown';
            data.url = url;
            data.title = document.title;
            data.source_title = document.title;
            data.context = getCleanDetailContext();
            
            FIELDS.forEach(field => {
                const input = document.getElementById(`dh-input-${field.key}`);
                if (input) {
                    if (field.type === 'checkbox') data[field.key] = input.checked;
                    else if (field.type === 'number') data[field.key] = parseFloat(input.value) || 0;
                    else data[field.key] = input.value;
                }
            });
            const fullAddress = (data['完整地址'] || data['地点'] || '').trim();
            if (fullAddress) {
                data['地点'] = fullAddress;
                data['完整地址'] = fullAddress;
                data.full_address = fullAddress;
            }
            data['出价次数'] = parseFloat(data['出价次数']) || 0;
            data['出价人数'] = parseFloat(data['出价人数']) || 0;
            data.bidCount = data['出价次数'];
            data.bid_count = data['出价次数'];
            data.bidderCount = data['出价人数'];
            data.bidder_count = data['出价人数'];
            data.deposit = parseFloat(data['保证金']) || 0;
            data.auction_start_time = data['开拍时间'];
            data.watch_count = parseFloat(data['围观人数']) || 0;
            data.reminder_count = parseFloat(data['提醒人数']) || 0;
            data.view_count = parseFloat(data['浏览次数']) || 0;
            data.gross_area_sqm = parseFloat(data['产权建筑面积']) || 0;
            data.ownership_share_ratio = parseFloat(data['产权份额比例']) || 1;
            data.court_name = data['法院名称'];
            data.case_number = data['案号'];
            return data;
        }

        function submitData() {
            calculateUnitPrice();
            const data = collectFormData();
            
            const needsInfo = (!data['所属小区'] || !data['最靠近商圈']) && data['地点'];
            if (needsInfo) {
                updateStatus('🔍 自动推断位置...', '#9c27b0');
                inferLocation(() => doSubmit());
            } else {
                doSubmit();
            }
        }
        
        function doSubmit() {
            calculateUnitPrice();
            const data = collectFormData();
            updateStatus('正在提交...', '#2196F3');
            const btn = document.getElementById('dh-btn-submit');
            if(btn) btn.disabled = true;
            
            fetchApi('/approve_area', data, (res) => {
                if(btn) btn.disabled = false;
                updateStatus('✅ 提交成功！', '#4caf50');
                // Flash Green
                const panel = document.getElementById('detail-helper-panel');
                if(panel) { panel.style.background = '#e8f5e9'; setTimeout(()=>panel.style.background='white', 500); }
                
                checkAutoSubmit(true); // Proceed to next if auto
            }, () => {
                if(btn) btn.disabled = false;
                updateStatus('❌ 提交失败', '#f44336');
            });
        }
        
        function checkAutoSubmit(forceNext = false) {
            if (!IS_AUTO_MODE) return;
            // In auto mode, logic might differ: usually we want to verify then submit
            // If called from scrollAndRetryArea, we submit result to AI queue (area_result)
            // But if called from doSubmit (Manual click or final step), we might want to fetch next.
            
            if (forceNext) {
                 setTimeout(() => {
                     updateStatus('🔄 获取下一任务...', '#2196f3');
                     fetchApi('/collection/details/next_task', {}, (task) => {
                         if (task && task.url) {
                             let nextUrl = task.url;
                             let separator = nextUrl.includes('?') ? '&' : '?';
                             if (!nextUrl.includes('auto_fix=1')) {
                                 nextUrl += separator + 'auto_fix=1';
                                 separator = '&';
                             }
                             // Persist uni_port if present in current URL
                             const currentPort = new URLSearchParams(window.location.search).get('uni_port');
                             if (currentPort && !nextUrl.includes('uni_port=')) {
                                 nextUrl += separator + 'uni_port=' + currentPort;
                             }
                             window.location.href = nextUrl;
                         } else {
                             updateStatus('🏁 完成', '#ff9800');
                             setTimeout(() => window.close(), 3000);
                         }
                     });
                 }, 500);
                 return;
            }
            
            // Auto-submit to AI Queue
            const data = collectFormData();
            if(data.id) {
                updateStatus('🤖 提交AI校验...', '#9c27b0');
                fetchApi('/area_result', data, () => {
                     updateStatus('✅ AI校验提交成功', '#4caf50');
                     setTimeout(() => checkAutoSubmit(true), 500);
                }, () => updateStatus('❌ AI提交失败', '#f44336'));
            }
        }
        
        function updateStatus(msg, color = '#666') {
            const el = document.getElementById('dh-status');
            if (el) { el.textContent = msg; el.style.color = color; }
        }

        // --- Init ---
        if (IS_AUTO_MODE) {
            log('自动模式 - 预滚动...', 'info');
            window.scrollTo({ top: document.body.scrollHeight * 0.75, behavior: 'smooth' });
            setTimeout(() => {
                window.scrollTo({ top: 0, behavior: 'smooth' });
                setTimeout(createPanel, 500);
            }, 2000);
        } else {
            setTimeout(createPanel, 500);
        }
    }

    // --- Main Entry ---
    
    // --- WORKER IDENTITY CHECK (Phase 3.1) ---
    // We use window.name (persists across same-tab navigations, even cross-origin!) to track the worker tab.
    // CRITICAL: DO NOT use GM_setValue for this — it's global and would poison ALL tabs!
    const IS_WORKER_TAB = (window.name === 'captcha_worker');
    const IS_WORKER_STANDBY = window.location.href.includes('__captcha_worker_master=1');
    const IS_SOLVER_BG = window.location.href.includes('__captcha_solver_bg=1');
    const IS_MANUAL_POPUP = window.location.href.includes('__captcha_manual_popup=1');
    
    console.log(`[Crow] Identity Check: IS_WORKER_TAB=${IS_WORKER_TAB}, IS_WORKER_STANDBY=${IS_WORKER_STANDBY}, IS_SOLVER_BG=${IS_SOLVER_BG}, hostname=${window.location.hostname}`);
    
    // Clean up stale global flag from previous buggy version
    GM_deleteValue('uni_captcha_worker_active');
    
    // PRIORITY 1: Captcha Standby Worker Page (Phase 3.1)
    if (IS_WORKER_STANDBY) {
        // Mark this tab as the worker via window.name (survives cross-origin navigation!)
        window.name = 'captcha_worker';
        
        document.body.innerHTML = `
            <div style="padding:40px; text-align:center; font-family:sans-serif;">
                <h2>🤖 法拍房：验证码专属打工页面 🤖</h2>
                <div id="cw-status" style="font-size:24px; color:#2196F3; font-weight:bold; margin:20px 0;">🟢 空闲待命处理中...</div>
                <p style="color:#666;">（此页面用于接收静默验证码请求。您可以将其脱离成独立窗口，放在屏幕边缘或第二显示器。<br>只要<b>不完全最小化</b>它就能生效。验证时这会跳转，验证完毕会自动跳回此处。）</p>
                <div id="cw-log" style="text-align:left; background:#1e1e1e; color:#a5d6ff; padding:15px; border-radius:8px; height:200px; overflow-y:auto; font-family:monospace; margin:20px auto; max-width:800px;"></div>
            </div>
        `;
        document.title = "🤖 验证码打工窗口";
        
        const cwLog = (msg) => {
            const el = document.getElementById('cw-log');
            if (el) {
                el.innerHTML += `<div>[${new Date().toLocaleTimeString()}] ${msg}</div>`;
                el.scrollTop = el.scrollHeight;
            }
        };
        
        cwLog("打工页已就绪！window.name='" + window.name + "' — 监听 uni_captcha_queue...");
        
        // Polling loop for queue
        setInterval(() => {
            const task = GM_getValue('uni_captcha_queue', null);
            if (task && task.url) {
                const age = Date.now() - task.timestamp;
                if (age < 60 * 1000) { // Process tasks up to 60s old (was 30s, too aggressive)
                    const statusEl = document.getElementById('cw-status');
                    if (statusEl) {
                        statusEl.innerText = "🚨 接收到验证任务，准备出击！";
                        statusEl.style.color = "#f44336";
                    }
                    cwLog(`收到跳转任务: ${task.url}`);
                    
                    // Consume the task
                    GM_deleteValue('uni_captcha_queue');
                    
                    // Jump! window.name persists through this navigation!
                    setTimeout(() => { window.location.href = task.url; }, 500);
                } else {
                    // Stale task, clean it up
                    cwLog(`丢弃过期任务 (age=${Math.round(age/1000)}s)`);
                    GM_deleteValue('uni_captcha_queue');
                }
            }
        }, 1000);
        
        return; // HALT — don't run dashboard/detail logic in this tab
    }
    
    // PRIORITY 2: Active Background Solver Page
    // Matches if: URL has __captcha_solver_bg param, OR this tab was previously the worker (window.name survives redirect)
    if (IS_SOLVER_BG || IS_WORKER_TAB) {
        console.log('[Worker] 背景验证码求解页面! IS_SOLVER_BG=' + IS_SOLVER_BG + ', IS_WORKER_TAB=' + IS_WORKER_TAB + ', URL=' + window.location.href);
        const workerStartTime = Date.now();
        
        // Wait 10s for page to fully load, then start checking if captcha is gone
        let returnAttempts = 0;
        setTimeout(() => {
            setInterval(() => {
                // Check if Master forcibly unlocked the system
                const forceUnlockTime = GM_getValue('uni_captcha_force_unlock', 0);
                if (forceUnlockTime > workerStartTime) {
                    console.log('[Worker] 🛑 接收到强制解锁信号，无条件中止工作并返回待命池！');
                    GM_setValue('uni_captcha_lock', 0);
                    window.location.href = 'https://sf.taobao.com/?__captcha_worker_master=1';
                    return;
                }
            
                const hasCaptcha = hasCaptchaChallenge(document);
                
                if (hasCaptcha) {
                    returnAttempts = 0;
                    return; // Captcha still present, solver is working
                }
                
                returnAttempts++;
                if (returnAttempts >= 3) { // 3 consecutive checks = 9s with no captcha
                    console.log('[Worker] 验证完毕，返回待命池...');
                    GM_setValue('uni_captcha_lock', 0);
                    window.location.href = 'https://sf.taobao.com/?__captcha_worker_master=1';
                }
            }, 3000);
        }, 10000);
        
        initCaptchaDetector();
        return; // HALT
    }

    // PRIORITY 2.5: Manual captcha popup page (single-instance fallback)
    if (IS_MANUAL_POPUP) {
        console.log('[Worker] 人工验证码弹窗页面已启动');

        let clearCount = 0;
        setInterval(() => {
            const forceUnlockTime = GM_getValue('uni_captcha_force_unlock', 0);
            if (forceUnlockTime > 0 && Date.now() - forceUnlockTime < 2 * 60 * 1000) {
                window.close();
                return;
            }

            const hasCaptcha = hasCaptchaChallenge(document);
            if (hasCaptcha) {
                clearCount = 0;
                return;
            }

            clearCount++;
            // 连续两轮无验证码则自动关闭，防止弹窗堆积
            if (clearCount >= 2) {
                window.close();
            }
        }, 5000);
    }

    // 1. If Master Page -> Show Dashboard
    if (isMaster) {
        window.addEventListener('load', createDashboard);
    } 
    // 2. If Detail Page -> Init Helper & Worker Check
    else if (isDetail) {
        initHelper();
        initWorker();
    }
    // 3. Login/Sec Page -> Auto-close or Alert
    else if (isLoginOrSec) {
        log('检测到验证/登录页面', 'warning');
        initCaptchaDetector();
    }
    // --- TAB Identity ---
    const TAB_ID = 'tab_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    console.log(`[Crow] Init Tab ID: ${TAB_ID}`);

    // --- Captcha Detector ---
    function initCaptchaDetector() {
        if (window.captcha_monitor_active) return;
        window.captcha_monitor_active = true;
        
        setInterval(() => {
            const hasCaptcha = hasCaptchaChallenge(document);
            
            if (hasCaptcha) {
                
                // --- Global Lock Check (Winner Takes All) ---
                const lastGlobalReport = GM_getValue('last_captcha_global_time', 0);
                const lockTabId = GM_getValue('captcha_solving_tab_id', null);
                const now = Date.now();
                
                // If lock exists and is valid (< 3 mins)
                if (now - lastGlobalReport < 3 * 60 * 1000) {
                    // If locked by ANOTHER tab
                     if (lockTabId && lockTabId !== TAB_ID) {
                         log(`⚠️ 验证码正在由页签 ${lockTabId} 处理，本页签 (${TAB_ID}) 自动避让。`, 'warning');
                         
                         // If I am a dedicated captcha page (Login/Sec) AND NOT the persistent worker, I should die.
                         if (isLoginOrSec && !IS_WORKER_TAB && !IS_SOLVER_BG) {
                             log('检测到多余验证窗口，3秒后自动关闭...', 'error');
                             setTimeout(() => window.close(), 3000); // Give user a moment to see why
                         }
                         return;
                     }
                     // If locked by ME, proceed (maybe retry?)
                }

                // Check if already reported recently locally (session)
                const lastReport = parseInt(sessionStorage.getItem('last_captcha_report') || '0');
                if (now - lastReport > 10000) { // Report every 10s max
                     log(`⚠️ 发现滑块验证码！Tab:${TAB_ID} 正在获取锁并请求处理...`, 'error');
                     
                     // CLAIM LOCK
                     GM_setValue('last_captcha_global_time', now);
                     GM_setValue('captcha_solving_tab_id', TAB_ID);
                     
                     // Visual Alert
                     let note = document.getElementById('unified-captcha-alert');
                     if(!note) {
                         note = document.createElement('div');
                         note.id = 'unified-captcha-alert';
                         note.style.cssText = 'position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:999999;background:red;color:white;padding:15px;font-size:20px;border-radius:5px;font-weight:bold;';
                         note.textContent = `⚠️ 正在处理验证码 (Tab: ${TAB_ID})`;
                         document.body.appendChild(note);
                     }
                      
                     fetchApi('/report_captcha', {
                         url: window.location.href,
                         timestamp: Date.now()
                     }, (res) => {
                         if(res.status === 'solving') {
                            if(note) note.textContent = '🤖 后端正在尝试自动过滑块... 请勿操作鼠标';
                         }
                     });
                     
                     sessionStorage.setItem('last_captcha_report', Date.now());
                }
            }
        }, 1000);
    }

})();
