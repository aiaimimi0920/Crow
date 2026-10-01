from __future__ import annotations
import logging
import glob
import json
import os
import random
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk

from src.data_fixer_context import AI_AVAILABLE, DATAS_DIR, FIELDS_SCHEMA, INFERABLE_FIELDS, logger
from src.collection.adapters.taobao_solver_target import _is_web_target_domain, _split_web_target_url


logger = logging.getLogger(__name__)


class DataFixerAppPart01:
    def __init__(self, root):
        self.root = root
        self.root.title("批量数据修复工具 (面积 & 小区)")
        self.root.geometry("1150x600")

        self.pending_items = []
        self.display_items = []
        self.task_queue = []
        self.is_scraping = False
        self.all_selected = False

        self.row_widgets = []
        self.next_row_id = 0

        # AI verification queue
        self.ai_verify_queue = []
        self.ai_verify_running = False
        self.ai_approved_count = 0
        self.ai_rejected_count = 0
        if AI_AVAILABLE:
            threading.Thread(target=self.ai_verify_worker, daemon=True).start()

        self.setup_ui()
        self.scan_missing_data()
        self.start_http_server()

        self.root.after(500, self.check_pending_items)

    def setup_ui(self):
        # Header
        header = ttk.Frame(self.root)
        header.pack(fill='x', padx=10, pady=5)

        ttk.Label(header, text="批量数据修复工具 (面积 & 小区)", font=('Arial', 14, 'bold')).pack(side='left')
        self.status_label = ttk.Label(header, text="待处理: 0 | 队列: 0")
        self.status_label.pack(side='right')

        # Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=10, pady=5)

        self.start_btn = ttk.Button(control_frame, text="▶ 开始自动抓取", command=self.start_scraping)
        self.start_btn.pack(side='left', padx=5)

        self.pause_btn = ttk.Button(control_frame, text="⏸ 暂停抓取", command=self.pause_scraping, state='disabled')
        self.pause_btn.pack(side='left', padx=5)

        ttk.Button(control_frame, text="🔄 重新扫描", command=self.scan_missing_data).pack(side='left', padx=5)

        self.scraping_status = ttk.Label(control_frame, text="状态: 待命", foreground='gray')
        self.scraping_status.pack(side='right', padx=10)

        # AI stats label
        self.ai_stats_label = ttk.Label(control_frame, text="AI通过: 0", foreground='green')
        self.ai_stats_label.pack(side='right', padx=10)

        # Main PanedWindow
        main_paned = ttk.PanedWindow(self.root, orient='vertical')
        main_paned.pack(fill='both', expand=True, padx=10, pady=5)

        # Top Pane: List Container + Buttons
        top_pane = ttk.Frame(main_paned)
        main_paned.add(top_pane, weight=3)

        # Headers moved to scrollable_frame


        ttk.Separator(top_pane, orient='horizontal').pack(fill='x', pady=2)

        # Canvas for scrolling
        canvas_frame = ttk.Frame(top_pane)
        canvas_frame.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        xscrollbar = ttk.Scrollbar(canvas_frame, orient='horizontal', command=self.canvas.xview)

        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=scrollbar.set, xscrollcommand=xscrollbar.set)

        # Mouse wheel scrolling (Vertical)
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        # Shift+Mouse wheel (Horizontal) - optional

        xscrollbar.pack(side='bottom', fill='x')
        self.canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Add Headers inside scrollable_frame
        self.next_row_idx = 1
        self.add_headers()

        button_frame = ttk.Frame(top_pane)
        button_frame.pack(fill='x', pady=5)

        self.select_all_btn = ttk.Button(button_frame, text="☐ 全选", command=self.toggle_select_all)
        self.select_all_btn.pack(side='right', padx=5)

        ttk.Button(button_frame, text="✅ 批量批准选中", command=self.batch_approve).pack(side='right', padx=5)
        ttk.Button(button_frame, text="⏭ 跳过选中", command=self.skip_selected).pack(side='right', padx=5)
        ttk.Button(button_frame, text="🗑 一键清空", command=self.clear_all).pack(side='left', padx=5)

        # Bottom Pane: Log
        log_pane = ttk.LabelFrame(main_paned, text="日志 (可拖动调整大小)")
        main_paned.add(log_pane, weight=1)

        self.log_text = tk.Text(log_pane, height=8, state='disabled')
        self.log_text.pack(fill='both', expand=True, padx=5, pady=5)

    def add_headers(self):
        # Header row 0
        col = 0
        ttk.Label(self.scrollable_frame, text="✓", width=3).grid(row=0, column=col, sticky='w', padx=1)
        col += 1
        ttk.Label(self.scrollable_frame, text="地址/标题", width=25, anchor='w').grid(row=0, column=col, sticky='w', padx=3)
        col += 1

        # Dynamic headers from schema
        for field in FIELDS_SCHEMA:
            if field.get('hidden'): continue
            width = field.get('width', 10)
            ttk.Label(self.scrollable_frame, text=field['label'], width=width, anchor='w').grid(row=0, column=col, sticky='w', padx=3)
            col += 1

        ttk.Label(self.scrollable_frame, text="上下文 / 状态", width=30, anchor='w').grid(row=0, column=col, sticky='w', padx=3)
        col += 1
        ttk.Label(self.scrollable_frame, text="操作", width=10).grid(row=0, column=col, sticky='w', padx=3)
        col += 1

        ttk.Separator(self.scrollable_frame, orient='horizontal').grid(row=0, column=0, columnspan=col, sticky='ew', pady=2)

    def scan_missing_data(self):
        self.task_queue = []

        # Scan root and archive
        root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
        archive_files = glob.glob(os.path.join(DATAS_DIR, 'archive', '**', '*.json'), recursive=True)
        all_files = root_files + archive_files

        file_count = 0
        for json_file in all_files:
            file_count += 1
            if file_count % 100 == 0:
                logger.info("[SCAN] Scanned %s/%s files...", file_count, len(all_files))

            if "model_config.json" in json_file or "monitor_state.json" in json_file or "sniff_progress.json" in json_file:
                continue

            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                items = data if isinstance(data, list) else [data]

                for item in items:
                    # Removed is_processed check to scan ALL historic data

                    # Skip if manually checked
                    if item.get('manual_checked'):
                        continue

                    # Old logic replaced by generic loop below
                    # if area_ok and comm_ok:
                    #     continue

                    # Needs fix
                    url = item.get('原始网站', '')
                    if _is_web_target_domain(_split_web_target_url(url), "taobao.com"):
                        item_id = item.get('id', 'unknown')
                        location = item.get('地点', '') or item.get('所属小区', '')
                        if location:
                            title = f"[{item_id}] {location[:25]}"
                        else:
                            title = f"ID:{item_id}"

                        missing_fields = []
                        # Check all fields in schema
                        for field in FIELDS_SCHEMA:
                            key = field['key']
                            # Skip allow-null fields or specialized logic if needed
                            if field.get('readonly'): continue # Skip readonly like id, url, unit price logic handled elsewhere

                            is_missing = False

                            # Inject source file path for offline processing
                            item['json_file'] = json_file

                            val = item.get(key)
                            is_missing = False

                            if field['type'] == 'number':
                                # For numbers, 0 might be valid (e.g. start price 0?),
                                # but usually for area/price it means missing/invalid in this context.
                                # Exception: '竞拍人数', '出价人数' can be 0.
                                if key in ['竞拍人数', '出价人数']:
                                    if val is None or val == "": is_missing = True
                                elif key in ['单价']: # Auto-calc, ignore
                                    pass
                                else:
                                    if not val or float(val) == 0: is_missing = True

                            elif field['type'] == 'checkbox':
                                 # boolean false is valid, so check for None
                                 if val is None: is_missing = True

                            else: # text
                                if not val or val == "null" or val == "":
                                    is_missing = True

                            if is_missing:
                                missing_fields.append(field['label'])

                        # If no missing fields, skip
                        if not missing_fields:
                            continue

                        # --- Smart Routing: AI-inferable vs Scrape-required ---
                        inferable_missing = [f for f in missing_fields if f in INFERABLE_FIELDS]
                        scrape_missing = [f for f in missing_fields if f not in INFERABLE_FIELDS]

                        # If has inferable missing fields AND has address -> queue for AI
                        if inferable_missing and item.get('地点'):
                            self.queue_for_ai_verification(item, row_id=None, priority=False)

                        # Only add to scraper queue if there are fields that REQUIRE web scraping
                        if scrape_missing:
                            self.task_queue.append({
                                'url': url,
                                'title': title[:40],
                                'id': item_id,
                                'json_file': json_file,
                                'missing': missing_fields,
                                'dataset_item': item
                            })
            except Exception:
                pass

        ai_queue_count = len(self.ai_verify_queue)
        scrape_count = len(self.task_queue)
        self.log(f"扫描完成：AI推断队列 {ai_queue_count} 条 | 爬虫队列 {scrape_count} 条")
        logger.info(
            "[SCAN] Found %s files. AI infer queue: %s, Scraper queue: %s",
            len(all_files),
            ai_queue_count,
            scrape_count,
        )
        if scrape_count == 0:
            logger.warning(
                "[SCAN] WARNING: Scraper queue is empty. "
                "Check if data is already complete or paths are correct."
            )
        self.update_status()

    def log(self, msg):
        def _log():
            try:
                self.log_text.config(state='normal')
                self.log_text.insert('end', f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                self.log_text.see('end')
                self.log_text.config(state='disabled')
            except Exception:
                pass
        self.root.after(0, _log)

    def get_next_task(self):
        if not self.is_scraping:
            return {'url': None, 'paused': True}

        while self.task_queue:
            # Random selection instead of sequential
            task = random.choice(self.task_queue)

            # Check if task is still needed (e.g. fixed by background AI)
            item = task.get('dataset_item')
            needed = True
            if item:
                needed = False
                for m in task.get('missing', []):
                    if m in INFERABLE_FIELDS:
                        # Check if inferable field is still empty
                        val = item.get(m)
                        if not val or str(val).lower() in ['none', 'null', '']: needed = True
                    else:
                        # Non-inferable field (price, area, etc.): always needs scraping
                        needed = True

            if not needed:
                 # self.log(f"[跳过] 已由后台修复: {task.get('title')[:10]}...")
                 self.task_queue.remove(task)
                 self.root.after(0, self.update_status)
                 continue

            self.task_queue.remove(task)
            self.root.after(0, self.update_status)
            return task
        return {'url': None}

    def add_item(self, data):
        """Add item from userscript (thread-safe)"""
        # Log received data for debugging
        logger.debug(
            "[DEBUG] Received: id=%s, url=%s...",
            data.get('id'),
            data.get('url')[:50] if data.get('url') else 'N/A',
        )

        # Deduplication: check if this URL already exists in display_items
        data_url = data.get('url', '')
        for existing in self.display_items:
            existing_url = existing.get('url', '')
            # Compare URLs by extracting item ID from URL
            if data_url and existing_url and data_url == existing_url:
                logger.debug("[DEBUG] Skipping duplicate URL")
                return  # Skip duplicate

        # Also check pending items
        for pending in self.pending_items:
            if data_url and pending.get('url', '') == data_url:
                logger.debug("[DEBUG] Skipping duplicate in pending")
                return

        # Merge with task_queue info
        data_id = str(data.get('id', ''))

        for task in self.task_queue:
            task_id = str(task.get('id', ''))
            task_url = task.get('url', '')

            # Match by ID (Preferred) or URL (Fallback)
            is_match = False
            if data_id and task_id and data_id == task_id:
                is_match = True
            elif data_url and task_url and data_url.split('?')[0] == task_url.split('?')[0]: # Ignore params
                is_match = True

            if is_match:
                data['json_file'] = task.get('json_file')
                data['title'] = task.get('title') or data.get('title', '')
                # If coming from correct task, we rely on task's file info
                break


        self.pending_items.append(data)
        # Log keys for debug
        logger.debug("[DEBUG] Added item keys: %s", list(data.keys()))
        logger.debug("[DEBUG] Added to pending, total pending: %s", len(self.pending_items))

    def check_pending_items(self):
        while self.pending_items:
            item = self.pending_items.pop(0)
            self.add_to_display(item)

        self.update_status()
        self.root.after(500, self.check_pending_items)

    def add_to_display(self, item):
        self.display_items.append(item)
        row_id = self.next_row_id
        self.next_row_id += 1
        self.add_row(item, row_id)
        self.log(f"收到: {item.get('title', '')[:20]}... 面积: {item.get('建筑面积', 'N/A')}")

        # Queue for AI verification if area detected
        self.queue_for_ai_verification(item, row_id)

__all__ = ('DataFixerAppPart01',)
