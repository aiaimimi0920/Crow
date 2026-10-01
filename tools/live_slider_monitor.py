"""Live NC-slider hunt: cruise real Taobao SF pages with the production CaptchaSolver
until Taobao naturally serves a draggable NC slider, then prove the solver drags it.

Detection parity: we run the exact production `CaptchaSolver.solve()` path. A subclass
records whether a real slider was actually found and dragged, so we can distinguish:
  - healthy page (no captcha)  -> solve()=True, slider_found=False
  - x5 hard block / login       -> solve()=False, reason=manual_required, slider_found=False
  - real NC slider              -> slider_found=True; solve()=True means auto-passed.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import datetime
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.project_environment import require_env, setdefault_env

setdefault_env("CROW_CDP_ENDPOINT", "http://127.0.0.1:9223")

import requests
from src.captcha_solver import CaptchaSolver

CDP = require_env("CROW_CDP_ENDPOINT")
LOG_PATH = os.path.join(REPO, "output", "slider_monitor.jsonl")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def log(event: dict) -> None:
    event["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    line = json.dumps(event, ensure_ascii=False)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print("[MON] " + line, flush=True)


class MonitoredSolver(CaptchaSolver):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.slider_found = False
        self.drag_done = False

    def _find_slider(self):
        info = super()._find_slider()
        if info:
            self.slider_found = True
            log({"kind": "SLIDER_DETECTED", "selector": info.get("selector"),
                 "context": info.get("context"), "target": self.target_url})
        return info

    def _do_drag(self, start_x, start_y, distance):
        out = super()._do_drag(start_x, start_y, distance)
        if out is not None:
            self.drag_done = True
        return out


def close_stale_tabs():
    try:
        tabs = requests.get(f"{CDP}/json/list", timeout=5).json()
    except Exception:
        return
    for t in tabs:
        if t.get("type") != "page":
            continue
        url = (t.get("url") or "").lower()
        title = t.get("title") or ""
        if "punish" in url or "x5sec" in url or "验证码拦截" in title or "about:blank" in url:
            try:
                requests.get(f"{CDP}/json/close/{t.get('id')}", timeout=5)
            except Exception:
                pass


def fetch_detail_ids(limit=8):
    """Grab a few real auction item ids from the list page via the health cookie-HTTP probe."""
    try:
        from tools.taobao_login_health import check_taobao_health
        r = check_taobao_health(cdp_endpoint=CDP,
                                check_url="https://sf.taobao.com/list/50025969__2.htm")
        ids = (r.get("list_summary") or {}).get("first_ids") or []
        return [str(i) for i in ids[:limit]]
    except Exception as e:
        log({"kind": "fetch_ids_error", "error": str(e)})
        return []


def build_url_rotation():
    cats = ["50025969", "50025970", "50025971", "50025972", "200958"]
    locs = ["110101", "310101", "440101", "330101", "510101", ""]
    st = ["2", "1", "0", "3"]
    urls = []
    for c in cats:
        for p in (1, 2, 3):
            loc = random.choice(locs)
            q = f"st_param={random.choice(st)}&auction_start_seg=-1&page={p}"
            if loc:
                q = f"location_code={loc}&" + q
            urls.append(f"https://sf.taobao.com/list/{c}__2.htm?{q}")
    for did in fetch_detail_ids():
        urls.append(f"https://sf-item.taobao.com/sf_item/{did}.htm")
    random.shuffle(urls)
    return urls


def main():
    max_minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
    deadline = time.time() + max_minutes * 60
    log({"kind": "MONITOR_START", "cdp": CDP, "max_minutes": max_minutes})

    rotation = build_url_rotation()
    if not rotation:
        rotation = ["https://sf.taobao.com/list/50025969__2.htm"]
    idx = 0
    it = 0
    consec_hardblock = 0
    counts = {"healthy": 0, "hard_block": 0, "slider": 0, "other": 0}

    while time.time() < deadline:
        it += 1
        url = rotation[idx % len(rotation)]
        idx += 1
        if idx % len(rotation) == 0:
            rotation = build_url_rotation() or rotation

        close_stale_tabs()
        solver = MonitoredSolver(cdp_endpoint=CDP, target_url=url)
        try:
            result = solver.solve(max_attempts=6)
        except Exception as e:
            log({"kind": "solve_error", "url": url, "error": repr(e)})
            time.sleep(5)
            continue
        reason = solver.last_failure_reason

        if solver.slider_found:
            counts["slider"] += 1
            consec_hardblock = 0
            if result and solver.drag_done:
                log({"kind": "SLIDER_SOLVED", "url": url, "result": True,
                     "counts": counts, "iterations": it})
                log({"kind": "MONITOR_DONE", "outcome": "auto_passed_real_slider",
                     "counts": counts, "iterations": it})
                return 0
            else:
                log({"kind": "SLIDER_ATTEMPT_FAILED", "url": url,
                     "result": bool(result), "reason": reason, "counts": counts})
        elif result:
            counts["healthy"] += 1
            consec_hardblock = 0
            log({"kind": "healthy", "url": url, "iter": it, "counts": counts})
        elif reason == "manual_required":
            counts["hard_block"] += 1
            consec_hardblock += 1
            log({"kind": "hard_block_or_login", "url": url, "iter": it,
                 "consec": consec_hardblock, "counts": counts})
        else:
            counts["other"] += 1
            log({"kind": "other", "url": url, "reason": reason, "iter": it, "counts": counts})

        # Base pacing; back off when the site is heavily blocking (to fish for a soft NC slider).
        base = random.uniform(6, 14)
        if consec_hardblock >= 3:
            base += min(consec_hardblock * 8, 90)
        time.sleep(base)

    log({"kind": "MONITOR_DONE", "outcome": "timeout_no_slider_solved",
         "counts": counts, "iterations": it})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
