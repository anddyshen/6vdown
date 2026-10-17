@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  6vdown portable build script (lightweight)
echo ============================================
echo.

set "PY=python"
if exist ".venv-run\Scripts\python.exe" set "PY=.venv-run\Scripts\python.exe"
echo Python : %PY%
echo.

echo [1/4] Ensuring build tools ...
%PY% -m pip install pyinstaller pillow -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
if errorlevel 1 (
  %PY% -m pip install pyinstaller pillow >nul 2>&1
)

echo [2/4] Checking application icon ...
if not exist "assets\6vdown.ico" (
  echo       Generating assets\6vdown.ico...
  %PY% tools\generate_icon.py
)

echo [3/4] Cleaning previous build artifacts ...
if exist build rmdir /s /q build
if exist dist\6vdown.exe del /q dist\6vdown.exe

echo [4/4] Building lightweight portable single-file executable ...
%PY% -m PyInstaller --noconfirm --clean 6vdown.spec
if errorlevel 1 goto :err

echo.
echo ============================================
echo  Build Success!
echo  Portable Exe: dist\6vdown.exe
echo ============================================
echo.
pause
exit /b 0

:err
echo.
echo [ERROR] Build failed. Please check error output above.
pause
exit /b 1
