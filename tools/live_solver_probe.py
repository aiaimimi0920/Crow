import sys
import json
from pathlib import Path


REPO = str(Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.project_environment import require_env, setdefault_env

setdefault_env("CROW_CDP_ENDPOINT", "http://127.0.0.1:9223")

from src.captcha_solver import CaptchaSolver

target = sys.argv[1] if len(sys.argv) > 1 else "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
print(f"[RUNNER] target={target}")
print(f"[RUNNER] cdp={require_env('CROW_CDP_ENDPOINT')}")

solver = CaptchaSolver(cdp_endpoint=require_env("CROW_CDP_ENDPOINT"), target_url=target)

# Just inspect the current challenge state first (does the real page show a slider?).
pre = solver._preflight_current_challenge()
print("[RUNNER] preflight=" + json.dumps(pre, ensure_ascii=False))

# Now run the real solve path end-to-end.
result = solver.solve(max_attempts=3)
print(f"[RUNNER] solve_result={result}")
print(f"[RUNNER] last_failure_reason={solver.last_failure_reason}")
