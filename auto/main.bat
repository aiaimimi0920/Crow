@echo off
pushd "%~dp0.." >nul

if not defined FAPAI_DB_URL (
    set "FAPAI_DB_URL=postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
)
if not defined FAPAI_DB_ENABLED (
    set "FAPAI_DB_ENABLED=1"
)
if not defined FAPAI_DB_AUTO_CREATE (
    set "FAPAI_DB_AUTO_CREATE=1"
)
if not defined FAPAI_DB_ENABLE_POSTGIS (
    set "FAPAI_DB_ENABLE_POSTGIS=1"
)
if not defined FAPAI_DB_PREFER_RUNTIME_INDEX (
    set "FAPAI_DB_PREFER_RUNTIME_INDEX=1"
)
if not defined FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE (
    set "FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE=1"
)

REM 1. Prefer externally injected PYTHON_CMD for smoke/wrapper overrides
if defined PYTHON_CMD (
    echo [INFO] Using preset PYTHON_CMD: %PYTHON_CMD%
) else (
    REM 2. Prefer the project-local venv when available
    if exist "venv\Scripts\python.exe" (
        set "PYTHON_CMD=venv\Scripts\python.exe"
    ) else (
        REM 3. Fallback to system Python
        echo [INFO] Local venv not found, falling back to system Python...
        set "PYTHON_CMD=python"
    )
)

echo [INFO] Database dual-write target: %FAPAI_DB_URL%

REM Execute
call "%PYTHON_CMD%" tools/run_collection_api.py
set "FAPAI_MAIN_EXIT_CODE=%ERRORLEVEL%"
echo [INFO] main.bat finished with exit code %FAPAI_MAIN_EXIT_CODE%
popd >nul
pause
exit /b %FAPAI_MAIN_EXIT_CODE%
