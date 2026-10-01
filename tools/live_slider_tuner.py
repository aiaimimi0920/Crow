"""Single-shot NC slider drag tuner.

Grabs ONE fresh Taobao NC slider, performs ONE clean human-like CDP drag with a
tunable profile, and reports the exact NC verdict + diagnostics. Does not fall back
to userscript, does not reload, does not burn multiple challenges per run.

Usage:
  python tools/live_slider_tuner.py [profile_json]
Where profile_json overrides drag params, e.g.
  '{"total_time":[2.4,3.2],"tremor_y":1.2,"overshoot":6,"pre_pause":[0.5,0.9]}'
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
import datetime
from pathlib import Path

import requests
import websocket

REPO = str(Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.project_environment import getenv as project_getenv

CDP = project_getenv("CROW_CDP_ENDPOINT", "http://127.0.0.1:9223")
LOG_PATH = os.path.join(REPO, "output", "slider_tuner.jsonl")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

SLIDER_SELECTORS = ['#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]', '.btn_slide', '.nc-slider-btn']
TRACK_SELECTORS = ['.nc_scale', '.nc_wrapper', '#nc_1_n1t', '#nc_2_n1t', '.nc-lang-cnt']

DEFAULT_PROFILE = {
    "pre_pause": [0.6, 1.1],       # reaction time before pressing
    "press_hold": [0.12, 0.28],   # hold after mousedown before moving
    "total_time": [2.6, 3.8],     # total drag duration seconds
    "steps": [32, 48],            # real mice emit fewer samples than CDP floods
    "tremor_x": 0.6,
    "tremor_y": 1.4,
    "micro_pause_prob": 0.12,
    "micro_pause": [0.03, 0.11],
    "overshoot": [0.0, 3.0],      # px beyond target then settle back
    "settle_steps": [2, 5],
    "hold_before_release": [0.25, 0.6],
}

CATS = ["50025969", "50025970", "50025971", "50025972", "200958", "50026064", "50025967"]
LOCS = ["110101", "310101", "440101", "330101", "510101", "420101", "500101", ""]


def random_url():
    c = random.choice(CATS)
    p = random.randint(1, 12)
    st = random.choice(["0", "1", "2", "3", "4", "5"])
    loc = random.choice(LOCS)
    q = f"st_param={st}&auction_start_seg=-1&page={p}"
    if loc:
        q = f"location_code={loc}&" + q
    return f"https://sf.taobao.com/list/{c}__2.htm?{q}"


def log(event):
    event["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    print("[TUNER] " + json.dumps(event, ensure_ascii=False), flush=True)


def rng(spec):
    if isinstance(spec, (list, tuple)):
        return random.uniform(spec[0], spec[1])
    return spec


class CDPTab:
    def __init__(self, cdp, url):
        self.cdp = cdp.rstrip("/")
        r = requests.put(f"{self.cdp}/json/new?{requests.utils.quote(url, safe='/:?=&%._-~')}", timeout=12).json()
        self.id = r["id"]
        self.ws = websocket.create_connection(r["webSocketDebuggerUrl"], suppress_origin=True, max_size=None)
        self.ws.settimeout(15)
        self.mid = 0
        for dom in ("DOM.enable", "Runtime.enable", "Page.enable"):
            self.cmd(dom)
        self.cmd("Page.addScriptToEvaluateOnNewDocument", {"source":
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})

    def cmd(self, method, params=None):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    return {"__error__": msg["error"]}
                return msg.get("result", {})

    def evaluate(self, expr):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return (r.get("result") or {}).get("value")

    def mouse(self, mtype, x, y, buttons=0, click_count=0):
        params = {
            "type": mtype,
            "x": x,
            "y": y,
            "pointerType": "mouse",
            "modifiers": 0,
            "buttons": int(buttons),
        }
        if mtype in ("mousePressed", "mouseReleased"):
            params["button"] = "left"
            params["clickCount"] = click_count or 1
        elif mtype == "mouseMoved" and buttons:
            params["button"] = "left"
        self.cmd("Input.dispatchMouseEvent", params)

    def window_metrics(self):
        return self.evaluate(
            """({
              screenX: window.screenX,
              screenY: window.screenY,
              outerWidth: window.outerWidth,
              outerHeight: window.outerHeight,
              innerWidth: window.innerWidth,
              innerHeight: window.innerHeight,
              dpr: window.devicePixelRatio || 1
            })"""
        ) or {}

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            requests.get(f"{self.cdp}/json/close/{self.id}", timeout=5)
        except Exception:
            pass


FIND_JS = """
(function(){
  var ss=%s, ts=%s;
  function find(sel){for(var i=0;i<sel.length;i++){var e=document.querySelector(sel[i]);if(e&&e.offsetParent!==null){var r=e.getBoundingClientRect();if(r.width>5&&r.height>5)return {sel:sel[i],x:r.left,y:r.top,w:r.width,h:r.height,id:e.id||''};}}return null;}
  var s=find(ss), t=find(ts);
  var keys=[];
  try{ Object.keys(window).forEach(function(k){ if(/nc|captcha|AWSC|nvc|NoCaptcha|__nc/i.test(k)) keys.push(k); }); }catch(e){}
  return {slider:s, track:t, webdriver: navigator.webdriver, ncKeys: keys,
    hasNoCaptcha: !!(window.NoCaptcha||window.nc_token||window.AWSC),
    title: document.title, href: location.href, ready: document.readyState };
})()
""" % (json.dumps(SLIDER_SELECTORS), json.dumps(TRACK_SELECTORS))

VERIFY_JS = """
(function(){
  var t=(document.body&&document.body.innerText)?document.body.innerText:'';
  var c=document.querySelector('.nc-container');
  var cls=c&&c.className?String(c.className):'';
  var slider=document.querySelector('#nc_1_n1z,#nc_2_n1z,[id^="nc_"][id$="_n1z"],.btn_slide');
  var sliderVisible=!!(slider&&slider.offsetParent!==null);
  var err = (t.match(/error:[A-Za-z0-9]+/) || [''])[0];
  var ncOk = cls.indexOf('nc-success')!==-1;
  var explicitPass = (t.indexOf('验证通过')!==-1 || t.indexOf('验证成功')!==-1 || t.indexOf('验证已通过')!==-1)
    && t.indexOf('验证失败')===-1 && t.indexOf('以确保')===-1;
  var fail = t.indexOf('验证失败')!==-1 || t.indexOf('点击框体重试')!==-1 || t.indexOf('拖动未达标')!==-1 || !!err;
  var punish = (location.href.indexOf('/_____tmd_____/')!==-1 || location.href.indexOf('x5secdata=')!==-1)
    && !sliderVisible && t.indexOf('请按住滑块')===-1;
  var listReady=false;
  try{ listReady = document.querySelectorAll('a[href*="sf_item/"]').length>=3 && t.indexOf('验证失败')===-1; }catch(e){}
  var success = (ncOk || explicitPass || listReady) && !fail && !punish;
  return {success:success, fail:fail, punish:punish, sliderVisible:sliderVisible,
    listReady:listReady, cls:cls, err:err, statusSnippet:t.slice(0,180), title:document.title};
})()
"""


def human_track(distance, profile):
    """Return list of (frac, dwell_seconds) producing a human velocity curve."""
    steps = int(rng(profile["steps"]))
    total = rng(profile["total_time"])
    # ease in-out but asymmetric: quicker to mid, slow crawl at end
    fracs = []
    for i in range(1, steps + 1):
        r = i / steps
        # smootherstep with an end-bias so it decelerates hard near the gap
        eased = r * r * r * (r * (r * 6 - 15) + 10)
        fracs.append(eased)
    # per-step dwell derived from velocity (slower where delta small)
    dwells = []
    prev = 0.0
    for f in fracs:
        dv = max(f - prev, 1e-4)
        prev = f
        # base proportional to total/steps, inversely modulated so slow ends dwell longer
        base = total / steps
        dwell = base * (0.6 + 0.8 * (1 - dv * steps / 1.0 if dv * steps < 1 else 0.2))
        dwell = max(0.006, min(dwell, 0.09))
        dwells.append(dwell)
    return fracs, dwells


def do_drag(tab, slider, track, profile):
    sx = slider["x"] + slider["w"] / 2
    sy = slider["y"] + slider["h"] / 2
    track_w = track["w"] if track else 300
    distance = max(60, track_w - slider["w"] - 4)
    target_x = sx + distance

    # pre-approach with no button
    for k in range(random.randint(2, 4)):
        tab.mouse("mouseMoved", sx - random.uniform(15, 35) + k * 8, sy + random.uniform(-6, 6), buttons=0)
        time.sleep(random.uniform(0.03, 0.09))
    tab.mouse("mouseMoved", sx, sy, buttons=0)
    time.sleep(rng(profile["pre_pause"]))

    tab.mouse("mousePressed", sx, sy, buttons=1, click_count=1)
    time.sleep(rng(profile["press_hold"]))

    fracs, dwells = human_track(distance, profile)
    for f, dwell in zip(fracs, dwells):
        x = sx + distance * f + random.gauss(0, profile["tremor_x"])
        y = sy + random.gauss(0, profile["tremor_y"])
        tab.mouse("mouseMoved", x, y, buttons=1)
        time.sleep(dwell)
        if random.random() < profile["micro_pause_prob"]:
            time.sleep(rng(profile["micro_pause"]))

    # overshoot then settle back to exact target
    over = rng(profile["overshoot"])
    tab.mouse("mouseMoved", target_x + over, sy + random.gauss(0, profile["tremor_y"]), buttons=1)
    time.sleep(random.uniform(0.06, 0.14))
    for _ in range(int(rng(profile["settle_steps"]))):
        target_x -= random.uniform(0.5, over / 2)
        tab.mouse("mouseMoved", target_x, sy + random.gauss(0, 0.8), buttons=1)
        time.sleep(random.uniform(0.02, 0.05))
    tab.mouse("mouseMoved", sx + distance, sy, buttons=1)

    time.sleep(rng(profile["hold_before_release"]))
    tab.mouse("mouseReleased", sx + distance, sy, buttons=0, click_count=1)
    return {"distance": distance, "track_w": track_w, "slider_w": slider["w"], "mode": "cdp"}


def locate_slider_on_screen(tab, slider):
    """Screenshot the handle via CDP and locate it with pyautogui (avoids DPR math)."""
    import base64
    import tempfile
    from pathlib import Path
    import pyautogui
    clip = {
        "x": max(0, slider["x"] - 2),
        "y": max(0, slider["y"] - 2),
        "width": slider["w"] + 4,
        "height": slider["h"] + 4,
        "scale": 1,
    }
    shot = tab.cmd("Page.captureScreenshot", {"format": "png", "clip": clip, "fromSurface": True})
    data = shot.get("data") if isinstance(shot, dict) else None
    if not data:
        log({"kind": "screenshot_failed", "shot": shot})
        return None
    tmp = Path(tempfile.gettempdir()) / "fapai_nc_handle.png"
    tmp.write_bytes(base64.b64decode(data))
    try:
        box = pyautogui.locateOnScreen(str(tmp), confidence=0.72)
    except Exception as exc:
        log({"kind": "locate_failed", "error": repr(exc), "tmp": str(tmp)})
        try:
            box = pyautogui.locateOnScreen(str(tmp))
        except Exception as exc2:
            log({"kind": "locate_failed_exact", "error": repr(exc2)})
            return None
    if not box:
        log({"kind": "locate_miss", "tmp": str(tmp)})
        return None
    center = pyautogui.center(box)
    log({"kind": "locate_ok", "box": [box.left, box.top, box.width, box.height], "center": [center.x, center.y]})
    return center


def do_os_drag(tab, slider, track, profile):
    """OS-level mouse: generates real trusted input that CDP dispatch cannot."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        import pyautogui
    except ImportError:
        log({"kind": "os_drag_unavailable", "error": "pyautogui missing"})
        return None
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    tab.cmd("Page.bringToFront")
    time.sleep(0.45)
    located = locate_slider_on_screen(tab, slider)
    track_w = track["w"] if track else 300
    css_distance = max(60, track_w - slider["w"] - 4)
    metrics = tab.window_metrics()
    dpr = float(metrics.get("dpr") or 1) or 1.0
    if located is not None:
        sx, sy = float(located.x), float(located.y)
        distance = css_distance * dpr
    else:
        inner_w = float(metrics.get("innerWidth") or 0)
        inner_h = float(metrics.get("innerHeight") or 0)
        outer_w = float(metrics.get("outerWidth") or 0)
        outer_h = float(metrics.get("outerHeight") or 0)
        chrome_top_css = max(0.0, outer_h - (inner_h / dpr if dpr else inner_h))
        border_css = max(0.0, (outer_w - (inner_w / dpr if dpr else inner_w)) / 2)
        sx = (float(metrics.get("screenX") or 0) + border_css + slider["x"] + slider["w"] / 2) * dpr
        sy = (float(metrics.get("screenY") or 0) + chrome_top_css + slider["y"] + slider["h"] / 2) * dpr
        distance = css_distance * dpr
    log({"kind": "os_coords", "sx": sx, "sy": sy, "distance": distance, "dpr": dpr, "located": located is not None})
    pyautogui.moveTo(sx - random.uniform(20, 40), sy + random.uniform(-8, 8), duration=random.uniform(0.25, 0.5))
    time.sleep(rng(profile["pre_pause"]))
    pyautogui.moveTo(sx, sy, duration=random.uniform(0.2, 0.45))
    time.sleep(rng(profile["press_hold"]))
    pyautogui.mouseDown()
    time.sleep(rng(profile["press_hold"]))
    fracs, dwells = human_track(distance, profile)
    for f, dwell in zip(fracs, dwells):
        pyautogui.moveTo(
            sx + distance * f + random.gauss(0, profile["tremor_x"]),
            sy + random.gauss(0, profile["tremor_y"]),
            duration=0,
        )
        time.sleep(dwell)
        if random.random() < profile["micro_pause_prob"]:
            time.sleep(rng(profile["micro_pause"]))
    over = rng(profile["overshoot"])
    pyautogui.moveTo(sx + distance + over, sy, duration=0)
    time.sleep(0.08)
    pyautogui.moveTo(sx + distance, sy, duration=0.08)
    time.sleep(rng(profile["hold_before_release"]))
    pyautogui.mouseUp()
    return {"distance": distance, "track_w": track_w, "slider_w": slider["w"], "mode": "os", "sx": sx, "sy": sy}


def wait_for_slider(tab, timeout=12):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        info = tab.evaluate(FIND_JS)
        last = info
        if info and info.get("slider"):
            return info
        time.sleep(0.5)
    return last


def verify(tab, timeout=5.0):
    deadline = time.time() + timeout
    result = None
    while time.time() < deadline:
        result = tab.evaluate(VERIFY_JS)
        if result and (result.get("success") or result.get("fail") or result.get("punish") or result.get("listReady")):
            if result.get("fail") or result.get("punish"):
                return ("FAIL" if result.get("fail") else "PUNISH"), result
            if result.get("success") or result.get("listReady"):
                return "PASS", result
        time.sleep(0.4)
    return "UNKNOWN", result


def notify_auth_complete(target_url):
    api = project_getenv("CROW_COLLECTION_API", "http://127.0.0.1:8001").rstrip("/")
    try:
        resp = requests.post(
            api + "/api/collection/auth/complete",
            json={
                "source": "captcha_solver",
                "refresh_cookie_snapshot": False,
                "target_url": target_url,
            },
            timeout=5,
        )
        log({"kind": "auth_complete", "status": resp.status_code, "body": resp.text[:400]})
    except Exception as exc:
        log({"kind": "auth_complete_skipped", "error": repr(exc)})


def solve_with_production_solver(target_url, target_id=None):
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from src.captcha_solver import CaptchaSolver
    solver = CaptchaSolver(cdp_endpoint=CDP, target_url=target_url)
    if target_id:
        solver.target_id = str(target_id)
    ok = solver.solve(max_attempts=3)
    return ok, solver.last_failure_reason


def main():
    profile = dict(DEFAULT_PROFILE)
    if len(sys.argv) > 1:
        try:
            profile.update(json.loads(sys.argv[1]))
        except Exception as e:
            print("bad profile json:", e)
    max_nav = int(os.environ.get("TUNER_MAX_NAV", "20"))
    drag_mode = os.environ.get("TUNER_DRAG_MODE", "os").strip().lower()
    use_solver = os.environ.get("TUNER_USE_SOLVER", "1").strip().lower() not in {"0", "false", "no", "off"}
    log({"kind": "RUN_START", "profile": profile, "max_nav": max_nav, "drag_mode": drag_mode, "use_solver": use_solver})
    url = random_url()
    tab = CDPTab(CDP, url)
    try:
        for nav in range(max_nav):
            if nav > 0:
                url = random_url()
                tab.cmd("Page.navigate", {"url": url})
                time.sleep(1.2)
            info = wait_for_slider(tab, timeout=6)
            tab.cmd("Page.bringToFront")
            if not (info and info.get("slider")):
                title = (info or {}).get("title", "")
                href = (info or {}).get("href", url)
                punish = "punish" in (href or "") or "验证码拦截" in title
                log({"kind": "nav", "n": nav, "state": "punish" if punish else "healthy", "url": href or url})
                if punish:
                    time.sleep(random.uniform(1.5, 2.5))
                else:
                    time.sleep(random.uniform(0.4, 0.9))
                continue
            target_url = (info or {}).get("href") or url
            log({"kind": "SLIDER_READY", "nav": nav, "slider": info["slider"], "track": info.get("track"),
                 "webdriver": info.get("webdriver"), "hasNoCaptcha": info.get("hasNoCaptcha"),
                 "ncKeys": info.get("ncKeys"), "url": target_url})
            time.sleep(random.uniform(1.6, 2.4))
            if use_solver:
                try:
                    tab.ws.close()
                except Exception:
                    pass
                ok, reason = solve_with_production_solver(target_url, target_id=tab.id)
                verdict = "PASS" if ok else "FAIL"
                log({
                    "kind": "VERDICT",
                    "verdict": verdict,
                    "solver_ok": ok,
                    "solver_reason": reason,
                    "mode": "production_solve",
                    "url": target_url,
                })
                if ok:
                    notify_auth_complete(target_url)
                print("VERDICT=" + verdict, flush=True)
                print(f"SOLVER_OK={ok} REASON={reason}", flush=True)
                return 0 if ok else 1
            drag_fn = do_os_drag if drag_mode == "os" else do_drag
            drag_meta = drag_fn(tab, info["slider"], info.get("track"), profile)
            if drag_meta is None:
                log({"kind": "DRAG_UNAVAILABLE", "mode": drag_mode})
                return 3
            verdict, detail = verify(tab, timeout=6)
            log({"kind": "VERDICT", "verdict": verdict, "drag": drag_meta, "detail": detail})
            if verdict == "PASS":
                notify_auth_complete(target_url)
            print("VERDICT=" + verdict, flush=True)
            return 0 if verdict == "PASS" else 1
    finally:
        tab.close()
    log({"kind": "NO_SLIDER_IN_RUN", "max_nav": max_nav})
    print("VERDICT=NO_SLIDER", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
