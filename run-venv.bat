@echo off
setlocal
cd /d %~dp0

echo ============================================
echo  C2Down launcher (isolated venv)
echo ============================================

if not exist ".venv-run\Scripts\python.exe" (
  echo [0/3] Creating isolated venv ...
  python -m venv .venv-run
  if errorlevel 1 goto :err
)

echo [1/3] Installing deps into venv ...
".venv-run\Scripts\python.exe" -m pip install --upgrade pip
".venv-run\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo       Retry with default PyPI index...
  ".venv-run\Scripts\python.exe" -m pip install -r requirements.txt
)
if errorlevel 1 goto :err

echo [2/3] Verifying PySide6 import ...
".venv-run\Scripts\python.exe" -c "import PySide6.QtCore; print('PySide6 OK')"
if errorlevel 1 goto :err

echo [3/3] Starting C2Down ...
".venv-run\Scripts\python.exe" main.py
if errorlevel 1 goto :err

endlocal
exit /b 0

:err
echo.
echo Failed. Check messages above.
pause
exit /b 1
