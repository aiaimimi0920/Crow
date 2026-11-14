from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from src.archive_json_io import read_json
from src.archive_transaction import archive_transaction
from src.data_fixer_context import AI_AVAILABLE, FIELDS_SCHEMA, ToolTip

try:
    from src.data_fixer_context import get_model_pool
except ImportError:
    def get_model_pool():
        return []

logger = logging.getLogger(__name__)


class DataFixerAppPart02:
    def add_row(self, item, row_idx_unused):
        # Use next_row_idx logic
        row_idx = self.next_row_idx
        self.next_row_idx += 1

        row_widgets = {}
        row_widgets['idx'] = row_idx # keep calling it idx, but it's grid row

        col = 0

        # 1. Checkbox
        var = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(self.scrollable_frame, variable=var)
        chk.grid(row=row_idx, column=col, sticky='w', padx=1)
        row_widgets['start_chk'] = chk
        row_widgets['chk_var'] = var
        col += 1

        # 2. Title/Link
        title = item.get('title', '') or '无标题'
        link_btn = ttk.Button(self.scrollable_frame, text=title[:10], width=25,
                             command=lambda: self.open_chrome(item, auto=False)) # Manual open
        link_btn.grid(row=row_idx, column=col, sticky='w', padx=3)
        row_widgets['link_btn'] = link_btn
        col += 1

        # 3. Dynamic Fields
        row_widgets['vars'] = {}
        row_widgets['entries'] = {}

        for field in FIELDS_SCHEMA:
            if field.get('hidden'): continue

            key = field['key']
            val = item.get(key, '')
            if val is None: val = ''
            width = field.get('width', 10)

            w_var = tk.StringVar(value=str(val))
            row_widgets['vars'][key] = w_var

            if field.get('readonly'):
                state = 'readonly'
            else:
                state = 'normal'

            entry = ttk.Entry(self.scrollable_frame, textvariable=w_var, width=width, state=state)
            entry.grid(row=row_idx, column=col, sticky='w', padx=3)
            row_widgets['entries'][key] = entry

            col += 1

        # 4. Context
        context_text = ""
        full_context = ""
        missing = item.get('missing', [])
        if missing:
            context_text = f"缺: {','.join(missing)}"
            full_context = context_text
        else:
            full_context = item.get('context', '')
            context_text = full_context.replace('\n', ' ')[:30] if full_context else ''
        context_label = ttk.Label(self.scrollable_frame, text=context_text, width=30, anchor='w')
        context_label.grid(row=row_idx, column=col, sticky='w', padx=3)
        row_widgets['context_label'] = context_label
        # Hover tooltip shows full context
        if full_context:
            row_widgets['context_tooltip'] = ToolTip(context_label, full_context, wrap_length=500)
        col += 1

        # 5. Operations
        op_frame = ttk.Frame(self.scrollable_frame)
        op_frame.grid(row=row_idx, column=col, sticky='w', padx=3)

        approve_btn = ttk.Button(op_frame, text="✓", width=3,
                               command=lambda: self.approve_single(row_idx))
        approve_btn.pack(side='left', padx=1)

        infer_btn = ttk.Button(op_frame, text="推断", width=4,
                              command=lambda: self._infer_location_for_row(row_idx))
        infer_btn.pack(side='left', padx=1)

        del_btn = ttk.Button(op_frame, text="删", width=3,
                           command=lambda: self.remove_row_by_idx(row_idx))
        del_btn.pack(side='left', padx=1)

        row_widgets['op_frame'] = op_frame
        row_widgets['approve_btn'] = approve_btn
        row_widgets['infer_btn'] = infer_btn
        row_widgets['del_btn'] = del_btn
        row_widgets['item'] = item

        self.row_widgets.append(row_widgets)
        return row_widgets

    def _infer_location_for_row(self, idx):
        """Handle manual '推断' button click for a row"""
        target_widget = None
        for w in self.row_widgets:
            if w['idx'] == idx:
                target_widget = w
                break

        if not target_widget:
            return

        item = target_widget['item']
        address = item.get('地点', '')
        title = item.get('title', '')

        if not address:
            self.log(f"无法推断: 缺少地址信息 (ID={item.get('id')})")
            return

        def run_infer():
            try:
                # Update button state to indicate working
                if 'infer_btn' in target_widget and target_widget['infer_btn'].winfo_exists():
                    target_widget['infer_btn'].config(state='disabled', text='...')

                result = self._infer_location_ai(address, title)

                # Callback to update UI in main thread
                def update_ui():
                    if 'infer_btn' in target_widget and target_widget['infer_btn'].winfo_exists():
                        target_widget['infer_btn'].config(state='normal', text='推断')

                    if result:
                        vars_dict = target_widget['vars']
                        updated = []
                        if result.get('所属小区') and '所属小区' in vars_dict:
                            vars_dict['所属小区'].set(result['所属小区'])
                            item['所属小区'] = result['所属小区']
                            updated.append(f"小区={result['所属小区']}")

                        if result.get('最靠近商圈') and '最靠近商圈' in vars_dict:
                            vars_dict['最靠近商圈'].set(result['最靠近商圈'])
                            item['最靠近商圈'] = result['最靠近商圈']
                            updated.append(f"商圈={result['最靠近商圈']}")

                        if updated:
                            self.log(f"推断成功: {' '.join(updated)}")
                        else:
                            self.log("推断完成: 未找到有效信息")
                    else:
                        self.log("推断失败: AI未返回结果")

                self.root.after(0, update_ui)

            except Exception as e:
                self.log(f"推断出错: {e}")
                def reset_btn():
                    if 'infer_btn' in target_widget and target_widget['infer_btn'].winfo_exists():
                        target_widget['infer_btn'].config(state='normal', text='推断')
                self.root.after(0, reset_btn)

        import threading
        threading.Thread(target=run_infer, daemon=True).start()

    def approve_single(self, idx):
        """Handle manual 'Approve' (check) button click for a row"""
        target_widget = None
        found = False
        for w in self.row_widgets:
            if w['idx'] == idx:
                target_widget = w
                found = True
                break

        if not found:
            self.log(f"错误: 找不到行 {idx}")
            return

        item = target_widget['item']
        try:
            # Collect all dynamic fields
            field_vars = target_widget['vars']

            for field in FIELDS_SCHEMA:
                if field.get('hidden') or field.get('readonly'): continue

                key = field['key']
                if key in field_vars:
                    val = field_vars[key].get().strip()

                    # Type conversion if needed?
                    # For now keep string mostly, except numbers if critical
                    if field.get('key') == '建筑面积':
                         if val and val != '0':
                             try:
                                 item['建筑面积'] = float(val)
                             except Exception:
                                 self.log(f"警告: 建筑面积 {val} 不是有效数字")
                         else:
                             item['建筑面积'] = 0
                    else:
                        item[key] = val

            # Define save action
            def do_save():
                # Map back to legacy keys if needed
                if '所属小区' in item:
                     item['community'] = item['所属小区']

                # Mark as checked
                item['manual_checked'] = True
                item['is_processed'] = True

                # Save to JSON
                if self.save_record(item):
                    self.log(f"已保存: {item.get('title', '')[:20]}")
                    self.remove_row_by_idx(idx)
                else:
                    self.log(f"保存失败: {item.get('title', '')[:20]}")
                    # Re-enable button if failed
                    if 'approve_btn' in target_widget and target_widget['approve_btn'].winfo_exists():
                        target_widget['approve_btn'].config(state='normal')

            # Check for missing info -> Auto Infer (Gap Filling)
            needs_community = not item.get('所属小区')
            needs_bizarea = not item.get('最靠近商圈')
            needs_area = not item.get('建筑面积') or float(item.get('建筑面积', 0)) == 0

            address = item.get('地点')

            # Workflow 2: If manual save, check missing -> sub-prompts -> save. No Final Verify.
            if AI_AVAILABLE and ((address and (needs_community or needs_bizarea)) or needs_area):
                self.log("保存前自动补全数据...")
                if 'approve_btn' in target_widget and target_widget['approve_btn'].winfo_exists():
                    target_widget['approve_btn'].config(state='disabled')

                def run_auto_infer_save():
                    try:
                        updates = []
                        # 1. Location Inference
                        if address and (needs_community or needs_bizarea):
                            # Use pool 1 for interactive
                            pool_idx = 1 if len(get_model_pool()) > 1 else 0
                            inferred = self._infer_location_ai(address, item.get('title', ''))

                            if inferred:
                                if needs_community and inferred.get('所属小区'):
                                    item['所属小区'] = inferred['所属小区']
                                    updates.append(f"小区={inferred['所属小区']}")
                                if needs_bizarea and inferred.get('最靠近商圈'):
                                    item['最靠近商圈'] = inferred['最靠近商圈']
                                    updates.append(f"商圈={inferred['最靠近商圈']}")

                        # 2. Area Extraction
                        if needs_area:
                             extracted_area = self._infer_area_only_ai(item)
                             if extracted_area and extracted_area > 0:
                                 item['建筑面积'] = extracted_area
                                 updates.append(f"面积={extracted_area}")

                        if updates:
                            self.log(f"补全成功: {' '.join(updates)}")

                    except Exception as e:
                        self.log(f"自动补全失败: {e}")

                    # Always save, even if infer failed
                    self.root.after(0, do_save)

                import threading
                threading.Thread(target=run_auto_infer_save, daemon=True).start()
            else:
                do_save()

        except Exception as e:
            self.log(f"处理失败: {e}")
            logger.exception("处理失败")
            return

        if self.save_record(item):
            self.log(f"已批准: {item.get('id', 'N/A')}... 面积: {item.get('建筑面积')}, 小区: {item.get('所属小区')}")
            self.remove_row_by_idx(idx)
            # Remove from display_items
            if item in self.display_items:
                self.display_items.remove(item)
            self.update_status()
        else:
            self.log("保存失败，请检查日志")

    def batch_approve(self):
        to_approve = []
        for w in self.row_widgets:
            if w['checkbox'].get():
                to_approve.append(w)

        if not to_approve:
            self.log("没有选中任何项目")
            return

        count = 0
        for w in to_approve:
            if self.approve_single(w['idx']):
                 count += 1

        self.log(f"批量批准完成，共 {len(to_approve)} 个")

    def log(self, msg):
        try:
            self.log_text.config(state='normal')
            self.log_text.insert('end', f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.log_text.see('end')
            self.log_text.config(state='disabled')
        except Exception:
            pass

    def approve_external(self, data):
        """Approve item from external source (userscript manual mode)"""
        url = data.get('url')
        # Support full update if id is present
        item_id = data.get('id')

        target_item = None

        # Helper to check match
        def is_match(item):
            # 1. Match by ID
            if item_id and item.get('id') and str(item.get('id')) == str(item_id):
                return True
            # 2. Match by exact URL
            if item.get('url') == url:
                return True
            # 3. Match by base URL (ignore params)
            if url and item.get('url'):
                base_u1 = url.split('?')[0]
                base_u2 = item.get('url').split('?')[0]
                if base_u1 == base_u2:
                    return True
            return False

        # Check display items first
        for item in self.display_items:
            if is_match(item):
                target_item = item
                break

        # Check pending items
        if not target_item:
            for item in self.pending_items:
                if is_match(item):
                    target_item = item
                    break

        # Check task queue
        if not target_item:
            for item in self.task_queue:
                if is_match(item):
                    # Load full item data from JSON
                    try:
                        with archive_transaction(item['json_file'], read_only=True):
                            full_data = read_json(item['json_file'])
                            if isinstance(full_data, list):
                                for i in full_data:
                                    if str(i.get('id')) == str(item['id']):
                                        target_item = i
                                        target_item['json_file'] = item['json_file']
                                        break
                            else:
                                target_item = full_data
                                target_item['json_file'] = item['json_file']
                    except Exception:
                        pass
                    break

        # Keep finding if not found in memory - construct a minimal item to search in files
        if not target_item and item_id:
             target_item = {'id': item_id, 'url': url}

        if target_item:
            try:
                # Auto-fix missing 所属小区/最靠近商圈 via AI before saving
                address = data.get('地点', '')
                needs_community = not data.get('所属小区') or data.get('所属小区', '').strip() == ''
                needs_bizarea = not data.get('最靠近商圈') or data.get('最靠近商圈', '').strip() == ''

                if address and (needs_community or needs_bizarea) and AI_AVAILABLE:
                    self.log(f"位置推断中: {address[:30]}...")
                    try:
                        inferred = self._infer_location_ai(address, data.get('title', ''))
                        if inferred:
                            if needs_community and inferred.get('所属小区'):
                                data['所属小区'] = inferred['所属小区']
                                self.log(f"AI推断小区: {inferred['所属小区']}")
                            if needs_bizarea and inferred.get('最靠近商圈'):
                                data['最靠近商圈'] = inferred['最靠近商圈']
                                self.log(f"AI推断商圈: {inferred['最靠近商圈']}")
                    except Exception as e:
                        self.log(f"位置推断失败，直接保存: {e}")

                # Use new save_record method with full data
                if self.save_record(target_item, new_data=data):
                    title = data.get('title', target_item.get('title', 'Unknown'))
                    area = data.get('建筑面积', 0)
                    self.log(f"外部全量更新: {title[:20]}... 面积: {area}")

                    # Remove from display if it's there
                    for i, row_data in enumerate(self.row_widgets):
                        if is_match(row_data['item']):
                            self.remove_row_by_idx(row_data['idx'])
                            break

                    # Also remove from task_queue if present
                    for i, task in enumerate(self.task_queue):
                        if is_match(task):
                            self.task_queue.pop(i)
                            break
                    return True
            except Exception as e:
                self.log(f"外部批准失败: {e}")
                return False

        self.log(f"外部批准失败: 未找到对应任务或文件 URL={url}")
        return False

__all__ = ('DataFixerAppPart02',)
