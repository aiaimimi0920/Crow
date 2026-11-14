from __future__ import annotations

import glob
import json
import os
import re
from urllib.parse import urlsplit

from src.archive_json_io import read_json
from src.archive_transaction import archive_transaction
from src.data_fixer_context import AI_AVAILABLE, DATAS_DIR, HTTP_PORT

try:
    from src.data_fixer_context import get_model_pool, simple_ai_call
except ImportError:
    def get_model_pool():
        return []

    def simple_ai_call(*_args, **_kwargs):
        return ""


class DataFixerAppPart03:
    def _infer_full_info_ai(self, item):
        """Stage 1: Main Prompt to get ALL info (Community, BizArea, Area, etc.)"""
        address = item.get('地点', '')
        title = item.get('title', '')
        context = item.get('context', '')

        if not AI_AVAILABLE or (not address and not title):
            return None

        prompt = f"""任务：全面分析以下房产拍卖信息，提取或推断关键属性。

输入信息：
标题：{title}
地址：{address}
上下文内容：
{context[:2000]}

请仔细分析以上信息，返回以下字段的JSON数据：
1. "所属小区"：稳定位置索引名，优先输出小区、楼盘或院落名称；不要求官方名称，但同一小区或同一片房源应尽量输出同一个名字。不要输出城市、区县、道路门牌号、楼号、单元号、房号；如果无法稳定识别小区，可输出商圈、镇街或片区名。
2. "最靠近商圈"：该地址所属的商圈名称。
3. "建筑面积"：数字（平方米），无需单位。
4. "户型"：如“三室两厅”。
5. "房屋用途"：如“住宅”、“商业”、“办公”等。
6. "省份"：行政省份（如广东省）。
7. "城市"：行政城市（如广州市）。
8. "区"：行政区（如天河区）。
9. "市场评估价"：数字（元）。
10. "起拍价格"：数字（元）。
11. "成交价格"：数字（元），如未成交则为0或null。
12. "交易时间"：格式 YYYY/MM/DD HH:mm:ss。
13. "竞拍人数"：数字（报名人数）。
14. "出价人数"：数字（实际出价人数）。
15. "是否成交"：布尔值（true/false）。

返回JSON格式示例：
{{
    "所属小区": "xxx",
    "最靠近商圈": "xxx",
    "建筑面积": 0.0,
    "户型": "xxx",
    "房屋用途": "xxx",
    "省份": "xxx",
    "城市": "xxx",
    "区": "xxx",
    "市场评估价": 1000000,
    "区": "xxx",
    "市场评估价": 1000000,
    "起拍价格": 800000,
    "成交价格": 1200000,
    "交易时间": "2023/01/01 10:00:00",
    "竞拍人数": 5,
    "出价人数": 3,
    "是否成交": true
}}
注意：
- 如果不确定某个字段，请返回 null，不要猜测。
- 建筑面积：如果是部分产权（如1/2份额、50%份额），请务必按份额比例计算实际可交易面积（例如100平米的1/2份额应填50）。如果是全套拍卖，则填全套产权证面积。
- 价格请转换为纯数字（元），不要带“万”等单位。"""

        # Use pool 1 (Inference Pool)
        pool_idx = 1 if len(get_model_pool()) > 1 else 0
        self.log("执行全量推断 (Stage 1)...")

        try:
            ai_result = simple_ai_call(prompt, pool_idx=pool_idx)
            # Use DOTALL to match newlines and match greedily to handle nested braces
            json_match = re.search(r'\{.*\}', ai_result, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except json.JSONDecodeError:
                    self.log(f"解析JSON失败: {ai_result[:50]}...")
                    parsed = {}


                # Filter valid results
                result = {}
                # Location
                if parsed.get('所属小区'): result['所属小区'] = parsed['所属小区']
                if parsed.get('最靠近商圈'): result['最靠近商圈'] = parsed['最靠近商圈']
                if parsed.get('省份'): result['省份'] = parsed['省份']
                if parsed.get('城市'): result['城市'] = parsed['城市']
                if parsed.get('区'): result['区'] = parsed['区']

                # Property Details
                if parsed.get('户型'): result['户型'] = parsed['户型']
                if parsed.get('房屋用途'): result['房屋用途'] = parsed['房屋用途']

                # Numeric & Dates (Robust parsing)
                def parse_num(key):
                    val = parsed.get(key)
                    if val is not None:
                        try:
                            return float(str(val).replace(',', '').replace('元', ''))
                        except Exception:
                            pass
                    return None

                if parsed.get('建筑面积'):
                     area = parse_num('建筑面积')
                     if area and area > 0: result['建筑面积'] = area

                if parsed.get('市场评估价'): result['市场评估价'] = parse_num('市场评估价')
                if parsed.get('起拍价格'): result['起拍价格'] = parse_num('起拍价格')
                if parsed.get('成交价格'): result['成交价格'] = parse_num('成交价格')

                if parsed.get('竞拍人数') is not None: result['竞拍人数'] = int(parse_num('竞拍人数') or 0)
                if parsed.get('出价人数') is not None: result['出价人数'] = int(parse_num('出价人数') or 0)

                if parsed.get('交易时间'): result['交易时间'] = parsed['交易时间']
                if parsed.get('是否成交') is not None: result['是否成交'] = parsed['是否成交']

                return result
        except Exception as e:
            self.log(f"全量推断失败: {e}")

        return None

    def _infer_location_ai(self, address, title=''):
        """Use AI to infer 所属小区 and 最靠近商圈 from address."""
        if not AI_AVAILABLE or not address:
            return None

        prompt = f"""任务：根据以下房产地址，推断所属小区名称和最靠近的商圈。

地址：{address}
标题：{title}

要求：
1. 所属小区：返回稳定位置索引名，优先输出小区、楼盘或院落名称；不要求官方名称，但同一小区或同一片房源应尽量输出同一个名字。不要输出城市、区县、道路门牌号、楼号、单元号、房号；如果无法稳定识别小区，可输出商圈、镇街或片区名。
2. 最靠近商圈：返回该地址最靠近的商圈名称（如：望京、国贸、五道口等）。

返回JSON格式：{{"所属小区": "xxx", "最靠近商圈": "xxx"}}"""

        # Use pool index 1 for inference if available to avoid blocking main worker
        pool_idx = 1 if len(get_model_pool()) > 1 else 0
        self.log(f"AI推断中 (Pool-{pool_idx})...")

        ai_result = simple_ai_call(prompt, pool_idx=pool_idx)
        json_match = re.search(r'\{.*\}', ai_result, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except Exception:
                parsed = {}

            result = {}
            if parsed.get('所属小区'):
                result['所属小区'] = parsed['所属小区']
            if parsed.get('最靠近商圈'):
                result['最靠近商圈'] = parsed['最靠近商圈']
            return result if result else None
        return None

    def _infer_area_only_ai(self, item):
        """Stage 2 Helper: Extract ONLY area from context."""
        title = item.get('title', '')
        context = item.get('context', '')

        prompt = f"""任务：从以下房产拍卖信息中提取“建筑面积”。

标题：{title}
上下文：
{context[:1500]}

要求：
1. 返回纯数字（平方米），无需单位。
2. 如果是部分产权（如1/2份额），请计算实际可交易面积。
3. 如果无法找到，返回 null。

返回JSON：{{"建筑面积": 123.45}}"""

        try:
             # Use pool 0 (Verification Pool - Default)
             res = simple_ai_call(prompt)
             # Use DOTALL for robustness
             match = re.search(r'\{.*\}', res, re.DOTALL)
             if match:
                 try:
                    parsed = json.loads(match.group())
                 except Exception:
                    parsed = {}
                 val = parsed.get('建筑面积')
                 if val and float(val) > 0:
                     return float(val)
        except Exception:
             pass
        return None

    def _verify_final_ai(self, item, context=None):
        """Stage 3: Final Holistic Verification."""
        # Clean context for prompt
        if context is None:
            context = item.get('context', '')
        context = context[:2000]

        # Construct data summary
        data_summary = {
            "标题": item.get('title'),
            "小区": item.get('所属小区'),
            "面积": item.get('建筑面积'),
            "起拍价": item.get('起拍价格'),
            "评估价": item.get('市场评估价'),
            "成交价": item.get('成交价格')
        }

        prompt = f"""任务：终审房产拍卖数据准确性。

目标数据：
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

对应网页文本（节选）：
{context}

请核对“目标数据”是否与“网页文本”一致。
特别是：
1. 小区名称是否准确？(如果文本只有地址，请判断小区名是否合理)
2. 建筑面积是否准确？(注意区分产权面积和通过份额计算的面积)
3. 价格是否匹配？

返回JSON格式：
{{
    "approved": true/false,   // 如果数据基本准确（或无法证伪），返回 true
    "reason": "通过原因或拒绝原因",
    "corrections": {{}}       // 如果有明显错误，请在此修正，例如 {{"建筑面积": 100.0}}
}}"""

        try:
             res = simple_ai_call(prompt)
             match = re.search(r'\{.*\}', res, re.DOTALL)
             if match:
                 return json.loads(match.group())
        except Exception as e:
             self.log(f"终审失败: {e}")
        return None

    def get_item_by_id(self, item_id):
        """Find item by ID in memory or files"""
        item_id = str(item_id)

        # 1. Check Display Items
        for row in self.row_widgets:
            if str(row['item'].get('id')) == item_id:
                return row['item']

        # 2. Check Pending Items
        for item in self.pending_items:
            if str(item.get('id')) == item_id:
                return item

        # 3. Check Task Queue
        for item in self.task_queue:
            if str(item.get('id')) == item_id:
                # Load full if only partial
                if 'json_file' in item:
                     try:
                        with archive_transaction(item['json_file'], read_only=True):
                            full_data = read_json(item['json_file'])
                            if isinstance(full_data, list):
                                for i in full_data:
                                    if str(i.get('id')) == item_id:
                                        i['json_file'] = item['json_file']
                                        return i
                            else:
                                full_data['json_file'] = item['json_file']
                                return full_data
                     except Exception:
                         pass
                return item

        # 4. Scan files (Slow, but necessary for random access)
        # Optimization: maybe rely only on queue?
        # But user wants "Local Data" priority, implying if it exists anywhere, show it.
        # Let's limit scan to recent/priority if possible, or just scan all since dataset isn't huge yet?
        # Given "glob.glob" usage in save_record, we can replicate it.
        root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
        archive_files = glob.glob(os.path.join(DATAS_DIR, 'archive', '**', '*.json'), recursive=True)

        for j_file in root_files + archive_files:
            try:
                with archive_transaction(j_file, read_only=True):
                    data = read_json(j_file)
                    items = data if isinstance(data, list) else [data]
                    for i in items:
                        if str(i.get('id')) == item_id:
                            i['json_file'] = j_file
                            return i
            except Exception:
                pass

        return None

    def open_chrome(self, item, auto=False):
        url = item.get('url', '')
        if not url:
            # Try to reconstruct from ID if missing
            item_id = item.get('id')
            if item_id:
                url = f"https://sf.taobao.com/Item.htm?id={item_id}"
            else:
                self.log("无法打开链接：没有URL或ID")
                return

        # Treat stored URLs as untrusted data.  Never pass them through a
        # shell command: quotes and cmd metacharacters would otherwise allow
        # command injection from a corrupted or externally supplied record.
        import webbrowser

        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in str(url)):
            self.log("无法打开链接：URL 包含控制字符")
            return
        try:
            parsed_url = urlsplit(str(url))
        except ValueError:
            self.log("无法打开链接：URL 格式无效")
            return
        if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.netloc:
            self.log("无法打开链接：仅支持 HTTP/HTTPS 地址")
            return
        if '"' in str(url) or "'" in str(url):
            self.log("无法打开链接：URL 包含非法引号")
            return

        # Prepare URL with port and mode
        # Always inject port so helper knows where to submit
        port_param = f"uni_port={HTTP_PORT}"

        separator = '&' if '?' in url else '?'
        if port_param not in url:
            url += f"{separator}{port_param}"

        if auto:
            # Add auto_fix
            separator = '&' if '?' in url else '?'
            if 'auto_fix=1' not in url:
                url += f"{separator}auto_fix=1"
        else:
            # Manual open: strip auto_fix param if present (cleanup contaminated data)
            url = url.replace('auto_fix=1', '').replace('?&', '?').replace('&&', '&')
            if url.endswith('?') or url.endswith('&'):
                url = url[:-1]

        try:
            # webbrowser.open delegates to the registered browser without
            # constructing a command shell string.  The auto flag only
            # controls URL parameters; focus policy belongs to the browser.
            webbrowser.open(url, new=0, autoraise=not auto)
            self.log(f"已打开: {url[:60]}...")
        except Exception as e:
            self.log(f"打开浏览器失败: {e}")

    def pause_scraping(self):
        self.is_scraping = False
        self.start_btn.config(state='normal')
        self.pause_btn.config(state='disabled')
        self.scraping_status.config(text="状态: 已暂停", foreground='orange')
        self.log("抓取已暂停")

    def toggle_select_all(self):
        """Toggle select all / deselect all"""
        self.all_selected = not self.all_selected
        for row_data in self.row_widgets:
            row_data['checkbox'].set(self.all_selected)

        if self.all_selected:
            self.select_all_btn.config(text="☑ 取消全选")
        else:
            self.select_all_btn.config(text="☐ 全选")

    def skip_selected(self):
        to_remove = []
        for row_data in self.row_widgets:
            if row_data['checkbox'].get():
                to_remove.append(row_data['idx'])

        for idx in to_remove:
            self.remove_row_by_idx(idx)

        self.log(f"已跳过 {len(to_remove)} 条记录")
        self.all_selected = False
        self.select_all_btn.config(text="☐ 全选")

__all__ = ('DataFixerAppPart03',)
