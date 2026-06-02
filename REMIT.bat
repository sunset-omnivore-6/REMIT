@echo off
REM REMIT local dashboard launcher.
REM What the desktop shortcut runs. Double-click to start the app.

setlocal
cd /d "%~dp0"

REM Prefer a project-local virtualenv if it exists.
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

REM First run only: install dependencies if uvicorn isn't importable.
"%PYTHON%" -c "import uvicorn" 2>NUL
if errorlevel 1 (
    echo Installing dependencies for first run...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency install failed. Press any key to close.
        pause >NUL
        exit /b 1
    )
)

"%PYTHON%" run.py

REM If the server exits for any reason, keep the window open so the user
REM can read the traceback.
echo.
echo Server stopped. Press any key to close this window.
pause >NUL
