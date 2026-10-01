"""
讯飞 MaaS WebSocket API 连接测试脚本
验证 WebSocket 方式调用讯飞大模型是否正常工作。
密钥从项目根目录的 secrets.json 加载。
"""
import _thread as thread
import base64
import hashlib
import hmac
import json
import os
import ssl
import sys
from datetime import datetime
from pathlib import Path
from time import mktime
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

import websocket

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm_diagnostics import diagnostic_number, failure_kind

SECRETS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "secrets.json")


def load_secrets():
    if not os.path.exists(SECRETS_FILE):
        print(f"[ERROR] secrets.json not found: {SECRETS_FILE}")
        print("[ERROR] Copy secrets.example.json to secrets.json and fill in your keys.")
        raise SystemExit(1)
    with open(SECRETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


class WsParam(object):
    def __init__(self, app_id, api_key, api_secret, spark_url):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = urlparse(spark_url).netloc
        self.path = urlparse(spark_url).path
        self.spark_url = spark_url

    def create_url(self):
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        signature_origin = "host: " + self.host + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + self.path + " HTTP/1.1"

        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()

        signature_sha_base64 = base64.b64encode(signature_sha).decode("utf-8")
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature_sha_base64}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")

        return self.spark_url + "?" + urlencode(
            {
                "authorization": authorization,
                "date": date,
                "host": self.host,
            }
        )


def gen_params(appid, domain):
    return {
        "header": {"app_id": appid, "uid": "1234"},
        "parameter": {
            "chat": {
                "domain": domain,
                "temperature": 0.5,
                "max_tokens": 2048,
            }
        },
        "payload": {
            "message": {
                "text": [
                    {"role": "user", "content": "你好"},
                ]
            }
        },
    }


def build_handlers(app_id, model_id):
    def on_error(ws, error):
        print("### Error kind:", failure_kind(error))

    def on_close(ws, one, two):
        print("### Closed ###")

    def run(ws, *args):
        data = json.dumps(gen_params(appid=app_id, domain=model_id))
        print("Sending request")
        ws.send(data)

    def on_open(ws):
        thread.start_new_thread(run, (ws,))

    def on_message(ws, message):
        data = json.loads(message)
        code = data["header"]["code"]
        if code != 0:
            print(f"Error Code: {diagnostic_number(code)}")
            ws.close()
        else:
            choices = data["payload"]["choices"]
            status = data["header"]["status"]
            content = choices["text"][0]["content"]
            print(f"Received response chunk: {len(content)} characters")
            if status == 2:
                print("\nAnalysis Finished.")
                ws.close()

    return on_message, on_error, on_close, on_open


def main():
    secrets = load_secrets()
    app_id = secrets["app_id"]
    api_key = secrets["api_key"]
    api_secret = secrets["api_secret"]
    model_id = secrets["models"][0]["model_id"]
    ws_url = secrets.get("ws_url", "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat")

    ws_param = WsParam(app_id, api_key, api_secret, ws_url)
    final_url = ws_param.create_url()
    print("Connecting to configured WebSocket endpoint")

    on_message, on_error, on_close, on_open = build_handlers(app_id, model_id)
    ws = websocket.WebSocketApp(
        final_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})


if __name__ == "__main__":
    main()
