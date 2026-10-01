"""
批量面积修复工具
- HTTP 服务器接收油猴脚本发送的数据
- 滚动列表显示待审批条目
- 支持批量批准和单独批准
"""

import tkinter as tk

from tkinter import ttk, messagebox

import threading

import json

import os

import subprocess

import re

from http.server import HTTPServer, BaseHTTPRequestHandler

import glob

import random

from datetime import datetime

import logging

from src.llm_diagnostics import failure_kind

logger = logging.getLogger(__name__)

DATAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'datas')

HTTP_PORT = 5001

AI_REQUEST_INTERVAL = 5  # seconds between AI requests

FIELDS_SCHEMA = [
    {'key': 'id', 'label': 'ID', 'type': 'number', 'readonly': True},
    {'key': '市场评估价', 'label': '市场评估价', 'type': 'number'},
    {'key': '起拍价格', 'label': '起拍价格', 'type': 'number'},
    {'key': '成交价格', 'label': '成交价格', 'type': 'number'},
    {'key': '交易时间', 'label': '交易时间', 'type': 'text'},
    {'key': '原始网站', 'label': '原始网站', 'type': 'text', 'readonly': True},
    {'key': '是否成交', 'label': '是否成交', 'type': 'checkbox'},
    {'key': '竞拍人数', 'label': '竞拍人数', 'type': 'number'},
    {'key': '出价人数', 'label': '出价人数', 'type': 'number'},
    {'key': '地点', 'label': '地点', 'type': 'text'},
    {'key': '所属小区', 'label': '所属小区', 'type': 'text'},
    {'key': '省份', 'label': '省份', 'type': 'text'},
    {'key': '城市', 'label': '城市', 'type': 'text'},
    {'key': '区', 'label': '区', 'type': 'text'},
    {'key': '最靠近商圈', 'label': '最靠近商圈', 'type': 'text'},
    {'key': '建筑面积', 'label': '建筑面积', 'type': 'number', 'step': 0.01},
    {'key': '单价', 'label': '单价', 'type': 'number', 'readonly': True},
    {'key': 'status', 'label': '状态', 'type': 'text', 'readonly': True, 'width': 8},
    {'key': 'detail_captured', 'label': '已抓取', 'type': 'checkbox', 'readonly': True},
    {'key': 'is_processed', 'label': 'AI完毕', 'type': 'checkbox', 'readonly': True},
]

INFERABLE_FIELDS = {'所属小区', '最靠近商圈', '省份', '城市', '区'}

AI_AVAILABLE = False

try:
    from src.llm_helper import Ws_Param, get_model_pool, AIService
    import websocket
    import ssl

    def simple_ai_call(prompt, pool_idx=None, max_retries=3):
        """Standalone AI call with retry.
        Uses random model selection to leverage high concurrency capacity."""
        import time as _time
        MODEL_POOL = get_model_pool()
        if not MODEL_POOL:
            return "Error: No AI models configured"

        # Randomly select a model to distribute load
        # If pool_idx is specifically provided (e.g. for debug), use it, otherwise random
        if pool_idx is not None and 0 <= pool_idx < len(MODEL_POOL):
            config = MODEL_POOL[pool_idx]
            idx = pool_idx
        else:
            idx = random.randint(0, len(MODEL_POOL) - 1)
            config = MODEL_POOL[idx]

        logger.info("[AI] Using model_slot=%s", idx + 1)

        for attempt in range(max_retries):
            try:
                service = AIService(config)
                service.prompt = prompt
                service.final_result = ""

                wsParam = Ws_Param(config["app_id"], config["api_key"], config["api_secret"], config["ws_url"])
                wsUrl = wsParam.create_url()

                ws = websocket.WebSocketApp(wsUrl,
                                            on_message=service.on_message,
                                            on_error=service.on_error,
                                            on_close=service.on_close,
                                            on_open=service.on_open)
                ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=130, ping_timeout=120)

                result = service.final_result

                # Check for API error in result
                if 'ConcurrencyOverFlow' in result or 'Error' in result[:20]:
                    wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                    logger.warning(f"[AI_RETRY] API限流，{wait}s后重试 (attempt {attempt+1}/{max_retries})")
                    _time.sleep(wait)
                    continue

                # Cleanup markdown if present
                if "```json" in result:
                    result = result.split("```json")[1].split("```")[0].strip()
                elif "```" in result:
                    result = result.split("```")[1].split("```")[0].strip()
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 10 * (2 ** attempt)
                    logger.warning("[AI_RETRY] kind=%s，%ss后重试", failure_kind(e), wait)
                    _time.sleep(wait)
                else:
                    logger.error("[AI_FAIL] 重试%s次后仍失败 kind=%s", max_retries, failure_kind(e))
                    return ""

    AI_AVAILABLE = True
    logger.info("[AI] Standalone AI call initialized (independent from data_receiver)")
except ImportError as e:
    logger.warning("[WARNING] AI verification disabled kind=%s", failure_kind(e))

try:
    from src.avm.community_resolver import apply_community_resolution, load_default_community_index, resolve_community_name
except ImportError:
    apply_community_resolution = None
    load_default_community_index = None
    resolve_community_name = None

def normalize_community_fields(item):
    if not (apply_community_resolution and load_default_community_index and resolve_community_name):
        return item
    try:
        resolution = resolve_community_name(item, load_default_community_index())
        if resolution:
            apply_community_resolution(item, resolution)
    except Exception as exc:
        logger.warning(f"[COMMUNITY_NORMALIZE_WARN] {exc}")
    return item

class ToolTip:
    def __init__(self, widget, text='', wrap_length=400):
        self.widget = widget
        self.text = text
        self.wrap_length = wrap_length
        self.tip_window = None
        widget.bind('<Enter>', self._show)
        widget.bind('<Leave>', self._hide)

    def _show(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        # Keep within screen bounds
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()
        tw.wm_geometry(f'+{min(x, screen_w - self.wrap_length - 40)}+{min(y, screen_h - 300)}')
        label = tk.Label(tw, text=self.text, justify='left',
                         background='#ffffcc', foreground='#333',
                         relief='solid', borderwidth=1,
                         wraplength=self.wrap_length,
                         font=('Microsoft YaHei', 9),
                         padx=8, pady=6)
        label.pack()

    def _hide(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

    def update_text(self, text):
        self.text = text

class AreaFixerHandler(BaseHTTPRequestHandler):
    gui = None

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/area_result':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                if AreaFixerHandler.gui:
                    AreaFixerHandler.gui.add_item(data)
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
        elif self.path == '/api/approve_area':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                if AreaFixerHandler.gui:
                    # Run in main thread
                    AreaFixerHandler.gui.root.after(0, lambda: AreaFixerHandler.gui.approve_external(data))
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
        elif self.path == '/api/infer_location':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                address = data.get('address', '')
                title = data.get('title', '')

                result = {'所属小区': '', '最靠近商圈': ''}

                if address and AI_AVAILABLE and AreaFixerHandler.gui:
                    inferred = AreaFixerHandler.gui._infer_location_ai(address, title)
                    if inferred:
                        result.update(inferred)

                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == '/api/next_task':
            if AreaFixerHandler.gui:
                task = AreaFixerHandler.gui.get_next_task()
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(task).encode())
            else:
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'url': None}).encode())
        else:
            self.send_response(404)
            self.end_headers()

__all__ = [name for name in globals() if not name.startswith("__")]
