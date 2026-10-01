function crowSource_30_sniff_dashboard() {
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

}
