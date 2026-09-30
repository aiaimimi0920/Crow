@echo off
pushd "%~dp0.." >nul

if not defined CROW_DB_URL if not defined FAPAI_DB_URL (
    set "CROW_DB_URL=postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
    set "FAPAI_DB_URL=postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
)
if not defined CROW_DB_ENABLED if not defined FAPAI_DB_ENABLED (
    set "CROW_DB_ENABLED=1"
    set "FAPAI_DB_ENABLED=1"
)
if not defined CROW_DB_AUTO_CREATE if not defined FAPAI_DB_AUTO_CREATE (
    set "CROW_DB_AUTO_CREATE=1"
    set "FAPAI_DB_AUTO_CREATE=1"
)
if not defined CROW_DB_ENABLE_POSTGIS if not defined FAPAI_DB_ENABLE_POSTGIS (
    set "CROW_DB_ENABLE_POSTGIS=1"
    set "FAPAI_DB_ENABLE_POSTGIS=1"
)
if not defined CROW_DB_PREFER_RUNTIME_INDEX if not defined FAPAI_DB_PREFER_RUNTIME_INDEX (
    set "CROW_DB_PREFER_RUNTIME_INDEX=1"
    set "FAPAI_DB_PREFER_RUNTIME_INDEX=1"
)
if not defined CROW_DB_PREFER_CONTROL_PLANE_SOURCE if not defined FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE (
    set "CROW_DB_PREFER_CONTROL_PLANE_SOURCE=1"
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

echo [INFO] Database configuration uses CROW_DB_URL or its legacy alias

REM Execute
call "%PYTHON_CMD%" tools/run_collection_api.py
set "CROW_MAIN_EXIT_CODE=%ERRORLEVEL%"
echo [INFO] main.bat finished with exit code %CROW_MAIN_EXIT_CODE%
popd >nul
pause
exit /b %CROW_MAIN_EXIT_CODE%
