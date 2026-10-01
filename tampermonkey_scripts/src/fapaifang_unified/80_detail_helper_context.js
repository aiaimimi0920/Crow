function crowSource_80_detail_helper_context() {
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

}
