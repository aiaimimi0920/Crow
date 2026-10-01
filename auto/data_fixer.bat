@echo off
pushd "%~dp0.." >nul

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

REM Execute
call "%PYTHON_CMD%" src/data_fixer.py
set "CROW_DATA_FIXER_EXIT_CODE=%ERRORLEVEL%"
echo [INFO] data_fixer.bat finished with exit code %CROW_DATA_FIXER_EXIT_CODE%
popd >nul
pause
exit /b %CROW_DATA_FIXER_EXIT_CODE%
