function crowSource_110_dispatch_and_captcha() {
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

}
