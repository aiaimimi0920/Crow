function crowSource_70_detail_worker() {
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

}
