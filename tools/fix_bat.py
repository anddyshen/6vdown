import os

bat_text = (
    "@echo off\r\n"
    "setlocal\r\n"
    "cd /d \"%~dp0\"\r\n\r\n"
    "if exist \".venv-run\\Scripts\\python.exe\" (\r\n"
    "    \".venv-run\\Scripts\\python.exe\" main.py\r\n"
    "    goto :eof\r\n"
    ")\r\n\r\n"
    "if exist \".venv\\Scripts\\python.exe\" (\r\n"
    "    \".venv\\Scripts\\python.exe\" main.py\r\n"
    "    goto :eof\r\n"
    ")\r\n\r\n"
    "python main.py\r\n"
    "if errorlevel 1 (\r\n"
    "    echo.\r\n"
    "    echo Startup failed.\r\n"
    "    pause\r\n"
    ")\r\n"
)

with open(r"d:\Projects\c2down\run.bat", "wb") as f:
    f.write(bat_text.encode("ascii"))

print("run.bat generated successfully with Windows CRLF encoding")
