@echo off
setlocal
cd /d %~dp0

rem Prefer the working isolated venv if present (avoids Anaconda DLL issues)
set "PY=python"
if exist ".venv-run\Scripts\python.exe" set "PY=.venv-run\Scripts\python.exe"
echo Python : %PY%

echo ============================================
echo  6vdown one-file build script
echo ============================================
echo.

echo [1/5] Installing runtime deps ...
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo       Retry with default PyPI index...
  %PY% -m pip install -r requirements.txt
)
if errorlevel 1 goto :err

echo [2/5] Installing build tools (pyinstaller, pillow) ...
%PY% -m pip install pyinstaller pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo       Retry with default PyPI index...
  %PY% -m pip install pyinstaller pillow
)
if errorlevel 1 goto :err

echo [3/5] Generating icon (assets\6vdown.ico) ...
%PY% tools\gen_icon.py
if errorlevel 1 goto :err

echo [4/5] Cleaning old outputs ...
if exist build rmdir /s /q build
if exist dist\6vdown.exe del /q dist\6vdown.exe

echo [5/5] PyInstaller one-file build (may take minutes) ...
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name 6vdown ^
  --icon assets\6vdown.ico ^
  --exclude-module tkinter ^
  main.py
if errorlevel 1 goto :err

echo.
echo Build OK: dist\6vdown.exe
pause
exit /b 0

:err
echo.
echo Build failed. Check messages above.
pause
exit /b 1


