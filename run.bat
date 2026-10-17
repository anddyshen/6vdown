@echo off
setlocal
cd /d "%~dp0"

if exist ".venv-run\Scripts\python.exe" (
    ".venv-run\Scripts\python.exe" main.py
    goto :eof
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
    goto :eof
)

python main.py
if errorlevel 1 (
    echo.
    echo Startup failed.
    pause
)
