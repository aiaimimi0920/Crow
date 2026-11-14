from __future__ import annotations

import glob
import logging
import os
import threading
from copy import deepcopy
from http.server import HTTPServer

from src.archive_json_io import read_json, write_json, write_records
from src.archive_transaction import archive_transaction
from src.data_fixer_context import (
    DATAS_DIR,
    HTTP_PORT,
    AreaFixerHandler,
    normalize_community_fields,
)

logger = logging.getLogger(__name__)


class DataFixerAppPart05:
    def batch_approve(self):
        approved = 0
        to_remove = []

        for row_data in self.row_widgets:
            if row_data['checkbox'].get():
                item = row_data['item']
                try:
                    area = float(row_data['area_var'].get())
                    item['建筑面积'] = area
                    if self.save_area(item):
                        approved += 1
                        to_remove.append(row_data['idx'])
                except Exception:
                    pass

        for idx in to_remove:
            self.remove_row(idx)

        self.log(f"已批准 {approved} 条记录")
        self.all_selected = False
        self.select_all_btn.config(text="☐ 全选")

    def skip_selected(self):
        to_remove = []
        for row_data in self.row_widgets:
            if row_data['checkbox'].get():
                to_remove.append(row_data['idx'])

        for idx in to_remove:
            self.remove_row(idx)

        self.log(f"已跳过 {len(to_remove)} 条记录")
        self.all_selected = False
        self.select_all_btn.config(text="☐ 全选")

    def _partial_update_item(self, item, row_id, updates_dict):
        """Update item and GUI without removing row (for Stage 1)."""
        # Find the row by row_id
        for row_data in self.row_widgets:
            if row_data['idx'] == row_id:
                # Update UI vars dynamically
                if 'vars' in row_data:
                    for k, v in updates_dict.items():
                        if k in row_data['vars']:
                            try:
                                row_data['vars'][k].set(str(v))
                            except Exception:
                                pass

                # Update item data
                for k, v in updates_dict.items():
                    item[k] = v

                # Save to JSON
                if self.save_record(item, new_data=updates_dict):
                    title = item.get('title', '')[:20]
                    self.log(f"[AI-Stage1] 已更新: {title}... {updates_dict}")
                else:
                    self.log(f"[AI-Stage1] 保存失败: {item.get('title', '')[:20]}...")
                break

    def _auto_approve_item_update(self, item, row_id, updates_dict):
        """Auto approve an item after AI verification with key-value updates."""
        # Find the row by row_id
        for row_data in self.row_widgets:
            if row_data['idx'] == row_id:
                # Update UI vars dynamically
                if 'vars' in row_data:
                    for k, v in updates_dict.items():
                        if k in row_data['vars']:
                             try:
                                 row_data['vars'][k].set(str(v))
                             except Exception:
                                 pass

                # Update item data
                for k, v in updates_dict.items():
                    item[k] = v

                # Save to JSON
                if self.save_record(item, new_data=updates_dict):
                    title = item.get('title', '')[:20]
                    self.log(f"[AI自动] 已修复: {title}... {updates_dict}")
                    # Use remove_row (aliased to remove_row_by_idx usually, or check definition)
                    # If remove_row takes widget, we need to be careful.
                    # Assuming remove_row_by_idx is safer if available?
                    # But existing code used remove_row(row_id). logic likely: delete row_id.
                    if hasattr(self, 'remove_row_by_idx'):
                        self.remove_row_by_idx(row_id)
                    else:
                        self.remove_row(row_id)
                else:
                    self.log(f"[AI自动] 保存失败: {item.get('title', '')[:20]}...")
                break

    def _auto_approve_item(self, item, row_id, area):
        self._auto_approve_item_update(item, row_id, {'建筑面积': area})

    def _update_ai_stats(self):
        """Update AI stats label in GUI."""
        self.ai_stats_label.config(text=f"AI通过: {self.ai_approved_count} | 待定: {self.ai_rejected_count}")

    def save_record(self, item, new_data=None):
        """
        Save/Update record in JSON file.
        If new_data is provided, it updates fields in the record.
        """
        try:
            json_file = item.get('json_file')
            item_id = item.get('id')
            item_url = item.get('url', '')

            # Extract item ID from URL as fallback
            url_extracted_id = None
            if item_url:
                import re
                match = re.search(r'[?&]id=(\d+)', item_url)
                if match:
                    url_extracted_id = match.group(1)
                else:
                    match = re.search(r'sf_item/(\d+)', item_url)
                    if match:
                        url_extracted_id = match.group(1)

            # Use extracted ID if item_id is missing
            if not item_id and url_extracted_id:
                item_id = url_extracted_id
                # print(f"[DEBUG] Extracted ID from URL: {item_id}")

            if not json_file:
                # Try to find json_file by scanning datas dir
                # self.log(f"正在查找数据源文件...")
                found = False

                root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
                archive_files = glob.glob(os.path.join(DATAS_DIR, 'archive', '**', '*.json'), recursive=True)

                for j_file in root_files + archive_files:
                    try:
                        with archive_transaction(j_file, read_only=True):
                            temp_data = read_json(j_file)
                            temp_items = temp_data if isinstance(temp_data, list) else [temp_data]
                            for r in temp_items:
                                # Strict ID match only
                                if item_id and str(r.get('id')) == str(item_id):
                                    json_file = j_file
                                    item['json_file'] = j_file
                                    found = True
                                    # print(f"[DEBUG] Found file by ID: {j_file}")
                                    break
                    except Exception:
                        pass

                    if found:
                        break

            if not json_file:
                self.log(f"保存失败: 未找到对应的数据文件 (ID={item_id})")
                return False

            if not item_id:
                self.log("保存失败: 缺少有效的 item_id")
                return False

            with archive_transaction(json_file, read_only=True):
                data = read_json(json_file)
            original = deepcopy(data)

            items = data if isinstance(data, list) else [data]
            updated = False

            for record in items:
                record_id = str(record.get('id', ''))
                target_id = str(item_id)

                # STRICT ID MATCH ONLY
                if record_id and target_id and record_id == target_id:
                    # Update fields if new_data is provided
                    if new_data:
                        # Clean URL to prevent auto_fix pollution
                        if new_data.get('url'):
                             new_data['url'] = new_data['url'].replace('?auto_fix=1', '').replace('&auto_fix=1', '')

                        # Update all fields from new_data
                        for k, v in new_data.items():
                            if k not in ['id', 'json_file']: # Don't overwrite metadata unless necessary
                                record[k] = v
                        normalize_community_fields(record)

                        # Special handling for automatic fields
                        record['is_processed'] = True
                        record['manual_checked'] = True

                        # Auto calculate unit price
                        area = record.get('建筑面积')
                        if area:
                            try:
                                area_float = float(area)
                                if area_float > 0:
                                    deal_price = record.get('成交价格')
                                    start_price = record.get('起拍价格')
                                    price = deal_price if deal_price else start_price

                                    if price:
                                        record['单价'] = round(float(price) / area_float, 2)
                                else:
                                    record['单价'] = 0
                            except Exception:
                                pass

                    # Fallback: update 建筑面积 directly from item
                    elif '建筑面积' in item:
                         area_float = float(item['建筑面积'])
                         record['建筑面积'] = area_float
                         if area_float == 0:
                             record['manual_checked'] = True
                             record['单价'] = 0
                         else:
                             deal_price = record.get('成交价格') or record.get('起拍价格')
                             if deal_price:
                                 record['单价'] = round(deal_price / area_float, 2)

                    updated = True
                    break

            if updated:
                with archive_transaction(json_file):
                    if read_json(json_file) != original:
                        raise RuntimeError("数据已被其他写者更新，请重新加载后保存")
                    if isinstance(data, list):
                        write_records(json_file, data, indent=2)
                    else:
                        write_json(json_file, data, indent=2)
                return True
            else:
                self.log(f"保存失败: 未找到匹配的记录 (ID={item_id})")

        except Exception as e:
            self.log(f"保存失败: {e}")
            logger.exception("保存失败")

        return False

    def start_http_server(self):
        AreaFixerHandler.gui = self

        def run_server():
            server = HTTPServer(('127.0.0.1', HTTP_PORT), AreaFixerHandler)
            self.log(f"HTTP 服务器启动于 localhost:{HTTP_PORT}")
            server.serve_forever()

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()

__all__ = ('DataFixerAppPart05',)
