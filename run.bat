@echo off
setlocal
cd /d %~dp0

echo ============================================
echo  C2Down launcher (install deps then run)
echo ============================================

echo.
echo [1/2] Installing dependencies (PySide6, requests)...
echo       Using Tsinghua mirror; fallback to PyPI if failed.
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo       Retry with default PyPI index...
  python -m pip install -r requirements.txt
)
if errorlevel 1 goto :err

echo.
echo [2/2] Starting C2Down ...
python main.py
if errorlevel 1 goto :err

endlocal
exit /b 0

:err
echo.
echo Startup failed. Check messages above.
pause
exit /b 1

