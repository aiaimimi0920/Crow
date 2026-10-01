function crowSource_20_sniff_challenge() {
    
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
}
