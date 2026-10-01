function crowSource_60_slow_review() {
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
}
