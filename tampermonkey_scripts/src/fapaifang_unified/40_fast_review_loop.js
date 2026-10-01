function crowSource_40_fast_review_loop() {
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
    
}
