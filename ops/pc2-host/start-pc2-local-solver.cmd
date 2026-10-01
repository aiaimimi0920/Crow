@echo off
setlocal

set "CROW_API_BASE_URL=http://192.168.15.200:8001/api"
set "FAPAI_API_BASE_URL=http://192.168.15.200:8001/api"
set "CROW_CDP_ENDPOINT=http://127.0.0.1:9223"
set "FAPAI_CDP_ENDPOINT=http://127.0.0.1:9223"
set "CROW_NODE_ID=pc2"
set "FAPAI_NODE_ID=pc2"
set "CROW_REAL_TAOBAO_AUTO_SOLVER_ENABLED=1"
set "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED=1"
set "CROW_SOLVER_OS_MOUSE=1"
set "FAPAI_SOLVER_OS_MOUSE=1"
set "CROW_SOLVER_DISABLE_STEALTH=1"
set "FAPAI_SOLVER_DISABLE_STEALTH=1"
set "CROW_SOLVER_COOLDOWN_FAIL_THRESHOLD=10"
set "FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD=10"
set "CROW_SOLVER_COOLDOWN_SECONDS=180"
set "FAPAI_SOLVER_COOLDOWN_SECONDS=180"
set "CROW_SLIDER_RETRY_INTERVAL_SECONDS=5"
set "FAPAI_SLIDER_RETRY_INTERVAL_SECONDS=5"
set "CROW_LOCAL_SOLVER_POLL_SECONDS=5"
set "FAPAI_LOCAL_SOLVER_POLL_SECONDS=5"
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"

set "REPO=C:\fapaifang-worker\src"
set "PYTHON=C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe"
set "LOG_DIR=C:\fapaifang-worker\logs\codex-pc2-real"
set "LOG_FILE=%LOG_DIR%\solver-live-current.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
cd /d "%REPO%" || exit /b 1

> "%LOG_FILE%" echo {"event":"solver_launcher_boot","launcher":"cmd"}
"%PYTHON%" ".\tools\pc2_local_solver.py" --api-base-url "%CROW_API_BASE_URL%" --cdp-endpoint "%CROW_CDP_ENDPOINT%" --node-id "%CROW_NODE_ID%" >> "%LOG_FILE%" 2>&1
exit /b %errorlevel%
