function crowSource_10_sniff_collection() {
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
}
