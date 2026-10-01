function crowSource_100_detail_helper_actions() {
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
}
