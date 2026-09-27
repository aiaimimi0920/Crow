from __future__ import annotations
import logging
import json
import random
import re
import time
from tkinter import messagebox

from src.data_fixer_context import AI_AVAILABLE, INFERABLE_FIELDS
try:
    from src.data_fixer_context import simple_ai_call
except ImportError:
    def simple_ai_call(*_args, **_kwargs):
        return ""


logger = logging.getLogger(__name__)


class DataFixerAppPart04:
    def ai_verify_worker(self):
        """Background worker thread for AI verification with New Workflow Logic (W1/W3)."""
        import time
        import re

        # No delay between calls - rely on retry mechanism for failures
        OFFLINE_DELAY = 0
        ONLINE_DELAY  = 0

        while True:
            if not self.ai_verify_queue:
                time.sleep(2)
                continue

            # Get next item to verify
            verify_item = self.ai_verify_queue.pop(0)
            item = verify_item['item']
            row_id = verify_item['row_id']
            retry_count = verify_item.get('retry_count', 0)
            is_offline = (row_id is None)

            try:
                context = item.get('context')
                missing = item.get('missing', [])

                logger.info(f"[AI_WORKER] {'BG' if is_offline else 'UI'} | {(item.get('title') or '?')[:15]}... Missing={missing}")

                # --- Workflow 3: Historic Data / Partial Context (No Web Text) ---
                if not context:
                    # Can only fix Community/BizArea via Address
                    if item.get('地点'):
                        address = item.get('地点')
                        prompt = f"""任务：根据以下房产拍卖地址，推断该房产所属的小区名称、最靠近的商圈、以及省份/城市/区。

地址：{address}
标题：{item.get('title', '')}

要求：
1. 小区名称：返回稳定位置索引名，优先输出小区、楼盘或院落名称；不要求官方名称，但同一小区或同一片房源应尽量输出同一个名字。不要输出城市、区县、道路门牌号、楼号、单元号、房号；如果无法稳定识别小区，可输出商圈、镇街或片区名。
2. 最靠近商圈：根据地址所在区域，推断最近的商业圈/商圈名。
3. 省份、城市、区：从地址中提取行政区划。
4. 如果某项无法确定，返回 null。

返回JSON：
{{{{
    "所属小区": "xxx",
    "最靠近商圈": "xxx",
    "省份": "xxx",
    "城市": "xxx",
    "区": "xxx"
}}}}"""
                        try:
                            res = simple_ai_call(prompt)
                            match = re.search(r'\{.*\}', res, re.DOTALL)
                            if match:
                                parsed = json.loads(match.group())
                                # Collect non-null inferred values
                                inferred = {}
                                for k in ['所属小区', '最靠近商圈', '省份', '城市', '区']:
                                    v = parsed.get(k)
                                    if v and str(v).lower() not in ['null', 'none', '']:
                                        inferred[k] = v

                                if inferred:
                                    logger.info(f"[AI_W3] Address Infer: {address} -> {inferred}")
                                    item.update(inferred)

                                    if row_id is not None:
                                        self.root.after(0, lambda i=item, r=row_id, kv=inferred.copy(): self._partial_update_item(i, r, kv))
                                    else:
                                        # Offline: Verify then save
                                        self.log(f"[离线推断] {address[:20]} -> {list(inferred.keys())}，验证中...")
                                        temp_context = f"地址：{address}\n请判断以下推断是否合理。"
                                        verify_res = self._verify_final_ai(item, context=temp_context)

                                        if verify_res and verify_res.get('approved'):
                                            corrections = verify_res.get('corrections', {})
                                            if corrections:
                                                item.update(corrections)
                                                inferred.update(corrections)
                                            self.save_record(item, new_data=inferred)
                                            self.log(f"[离线修复] ✓ 已保存 (ID:{item.get('id')})")
                                        else:
                                            reason = verify_res.get('reason') if verify_res else 'N/A'
                                            self.log(f"[离线修复] ✗ 验证拒绝: {reason}")
                        except Exception as e:
                            logger.error(f"[AI_W3_ERROR] {e}")

                    # Fields like area/price can't be inferred without context
                    # Rate limit for offline tasks
                    time.sleep(OFFLINE_DELAY if is_offline else ONLINE_DELAY)
                    continue

                # --- Workflow 1: Auto-Scraped Data (Has Context) ---

                # Step 1: Full Inference (if not done)
                if not item.get('stage1_done'):
                    try:
                        full_res = self._infer_full_info_ai(item)
                        if full_res:
                            item.update(full_res)
                            # Update GUI immediately with what we found
                            self.root.after(0, lambda i=item, r=row_id, kv=full_res: self._partial_update_item(i, r, kv))
                        item['stage1_done'] = True
                    except Exception as e:
                        logger.error(f"[AI_W1_STEP1_ERROR] {e}")

                # Step 2: Gap Filling (Completing Data)
                # Re-evaluate missing
                if not item.get('所属小区'): missing.append('所属小区')
                if not item.get('建筑面积') or float(item.get('建筑面积', 0)) == 0: missing.append('建筑面积')

                updates_step2 = {}

                # 2.1 Location Fields Extraction (小区 + 商圈 + 省/市/区)
                has_missing_location = any(
                    not item.get(f) or str(item.get(f, '')).strip().lower() in ['none', 'null', '']
                    for f in ['所属小区', '最靠近商圈', '省份', '城市', '区']
                )
                if has_missing_location:
                    address = item.get('地点')
                    if address:
                        logger.info(f"[AI_W1_STEP2] Inferring location fields from: {address[:30]}")
                        prompt = f"""任务：根据以下房产拍卖地址，推断该房产所属的小区名称、最靠近的商圈、以及省份/城市/区。

地址：{address}
标题：{item.get('title', '')}

要求：
1. 小区名称：如果地址中包含小区、楼盘或院落名，直接提取为稳定位置索引名；否则输出可稳定复用的商圈、镇街或片区名。不要求官方名称，但同一小区或同一片房源应尽量输出同一个名字。不要输出城市、区县、道路门牌号、楼号、单元号、房号。
2. 最靠近商圈：根据地址所在区域，推断最近的商业圈/商圈名。
3. 省份、城市、区：从地址中提取行政区划。
4. 如果某项无法确定，返回 null。

返回JSON：
{{{{
    "所属小区": "xxx",
    "最靠近商圈": "xxx",
    "省份": "xxx",
    "城市": "xxx",
    "区": "xxx"
}}}}"""
                        try:
                            res = simple_ai_call(prompt)
                            match = re.search(r'\{.*\}', res, re.DOTALL)
                            if match:
                                parsed = json.loads(match.group())
                                for k in ['所属小区', '最靠近商圈', '省份', '城市', '区']:
                                    v = parsed.get(k)
                                    if v and str(v).lower() not in ['null', 'none', '']:
                                        # Only fill if currently empty
                                        cur = item.get(k)
                                        if not cur or str(cur).strip().lower() in ['none', 'null', '']:
                                            item[k] = v
                                            updates_step2[k] = v
                        except Exception as e:
                            logger.error(f"[AI_W1_STEP2_LOC_ERROR] {e}")

                # 2.2 Area Extraction
                area = item.get('建筑面积')
                if not area or float(area) == 0:
                     extracted_area = self._infer_area_only_ai(item)
                     if extracted_area and extracted_area > 0:
                         item['建筑面积'] = extracted_area
                         updates_step2['建筑面积'] = extracted_area

                # Update GUI with Step 2 results
                if updates_step2:
                     logger.info(f"[AI_W1_STEP2] Fill gaps: {updates_step2}")
                     self.root.after(0, lambda i=item, r=row_id, kv=updates_step2: self._partial_update_item(i, r, kv))

                # Step 3: Final Verification
                # Only if we have enough data to verify?
                # Or always verify?
                # User says: "Ask AI if this data is correct. If yes, Use it."

                verify_res = self._verify_final_ai(item)

                if verify_res and verify_res.get('approved'):
                    logger.info(f"[AI_W1_STEP3] APPROVED. Reason: {verify_res.get('reason')}")
                    # Auto Approve (Remove Row)
                    # We might have corrections in verify_res?
                    corrections = verify_res.get('corrections', {})
                    if corrections:
                        item.update(corrections)

                    self.ai_approved_count += 1
                    self.root.after(0, lambda i=item, r=row_id, kv=corrections: self._auto_approve_item_update(i, r, kv))

                else:
                    reason = verify_res.get('reason') if verify_res else "No Response"
                    logger.warning(f"[AI_W1_STEP3] REJECTED/UNCERTAIN. Reason: {reason}")
                    # We already did Partial Updates in Step 1 & 2.
                    # So the data is saved in file (if _partial_update saves).
                    # Row remains in GUI for manual review.
                    pass

            except Exception as e:
                error_msg = str(e)
                if 'Concurrency' in error_msg or 'concurrency' in error_msg.lower():
                    logger.warning(f"[AI_RETRY] 服务端并发限制，重新入队...")
                    self.ai_verify_queue.append({
                        'item': item,
                        'row_id': row_id,
                        'retry_count': retry_count + 1
                    })
                    time.sleep(30)  # Wait 30s on concurrency error
                else:
                    logger.error(f"[AI_WORKER_ERROR] {e}")

            # Update AI stats & rate limit
            self.root.after(0, self._update_ai_stats)
            time.sleep(OFFLINE_DELAY if is_offline else ONLINE_DELAY)

    def _update_ai_stats(self):
        """Update AI stats label in GUI."""
        self.ai_stats_label.config(text=f"AI通过: {self.ai_approved_count} | 待定: {self.ai_rejected_count}")

    def queue_for_ai_verification(self, item, row_id=None, priority=True):
        """Add item to AI verification queue. Auto-detects missing fields."""
        if not AI_AVAILABLE:
            return

        # Auto-detect missing fields from actual values
        missing = []
        for field_key in INFERABLE_FIELDS:
            val = item.get(field_key)
            if not val or str(val).strip().lower() in ['none', 'null', '']:
                missing.append(field_key)

        # Check area
        area = 0
        try:
            area = float(item.get('建筑面积', 0) or 0)
        except Exception:
            pass
        if area == 0:
            missing.append('建筑面积')

        # Check if area needs verification (has area but not yet verified)
        needs_area_verify = (area > 0 and not item.get('is_verified'))

        if not missing and not needs_area_verify:
            return  # Nothing to do

        # Set missing on item so worker knows what to fix
        item['missing'] = missing

        queue_entry = {
            'item': item,
            'row_id': row_id,
            'retry_count': 0
        }

        if priority:
            self.ai_verify_queue.insert(0, queue_entry)
            label = 'HighPriority'
        else:
            self.ai_verify_queue.append(queue_entry)
            label = 'LowPriority'

        logger.info(f"[AI_QUEUE] Adding {label}: {(item.get('title') or '?')[:30]}... Missing: {missing}")

    def sort_by_area(self):
        """Sort displayed items by whether they have a valid area (items with area first)."""
        if not self.row_widgets:
            self.log("没有可排序的条目")
            return

        # Clear current display
        for row_data in self.row_widgets:
            row_data['frame'].destroy()

        # Sort: items with valid area first, then by area value descending
        def sort_key(row_data):
            area = row_data['item'].get('建筑面积')
            if area and float(area) > 0:
                return (0, -float(area))  # Has area, sort by area desc
            return (1, 0)  # No area, put at end

        sorted_rows = sorted(self.row_widgets, key=sort_key)

        # Rebuild display with sorted order
        self.row_widgets = []
        for row_data in sorted_rows:
            self.add_row(row_data['item'], row_data['idx'])

        self.log(f"已按面积排序 (有效面积优先)")

    def skip_single(self, idx):
        """Skip single item"""
        self.remove_row_by_idx(idx)
        self.log("已跳过一条记录")

    def delete_single(self, idx):
        """Delete single item from display (doesn't affect JSON)"""
        self.remove_row_by_idx(idx)
        self.log("已删除一条记录（仅从显示中移除，不影响原数据）")

    def clear_all(self):
        """Clear all displayed items (doesn't affect JSON)"""
        count = len(self.row_widgets)
        # Destroy all row frames
        self.next_row_idx = 1
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.row_widgets = []
        self.add_headers()
        self.display_items.clear()
        self.pending_items.clear()
        self.update_status()
        self.log(f"已清空 {count} 条记录（仅从显示中移除，不影响原数据）")

    def remove_row_by_idx(self, idx):
        """Remove a row from display"""
        for i, row_data in enumerate(self.row_widgets):
            if row_data['idx'] == idx:
                # Destroy known widgets
                if 'start_chk' in row_data: row_data['start_chk'].destroy()
                if 'link_btn' in row_data: row_data['link_btn'].destroy()
                if 'context_label' in row_data: row_data['context_label'].destroy()
                if 'approve_btn' in row_data: row_data['approve_btn'].destroy()
                if 'del_btn' in row_data: row_data['del_btn'].destroy()
                if 'op_frame' in row_data: row_data['op_frame'].destroy()

                if 'entries' in row_data:
                    for entry in row_data['entries'].values():
                        entry.destroy()

                self.row_widgets.pop(i)
                # Also remove from display_items
                if 'item' in row_data:
                    item_to_remove = row_data['item']
                    for j, item in enumerate(self.display_items):
                        if id(item) == id(item_to_remove):
                            self.display_items.pop(j)
                            break
                break
        self.update_status()

    def update_status(self):
        remaining = len(self.task_queue)
        self.status_label.config(text=f"显示: {len(self.row_widgets)} | 队列剩余: {remaining}")

    def start_scraping(self):
        if not self.task_queue:
            messagebox.showinfo("提示", "没有待处理的任务")
            return

        self.is_scraping = True
        self.start_btn.config(state='disabled')
        self.pause_btn.config(state='normal')
        self.scraping_status.config(text="状态: 抓取中...", foreground='green')

        if self.task_queue:
            task = random.choice(self.task_queue)
            self.task_queue.remove(task)
            self.open_chrome(task, auto=True)
            self.log(f"开始自动抓取")

        self.update_status()

    def advance_to_next(self):
        """Auto-advance to next task in queue."""
        if not self.is_scraping:
            return
        if not self.task_queue:
            self.log("任务队列已空，自动抓取完成")
            self.pause_scraping()
            return

        task = random.choice(self.task_queue)
        self.task_queue.remove(task)
        self.open_chrome(task, auto=True)
        self.log(f"自动前进: 剩余 {len(self.task_queue)} 个任务")
        self.update_status()

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

__all__ = ('DataFixerAppPart04',)
