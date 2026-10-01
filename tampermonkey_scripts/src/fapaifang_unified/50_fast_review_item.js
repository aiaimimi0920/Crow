function crowSource_50_fast_review_item() {
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

}
