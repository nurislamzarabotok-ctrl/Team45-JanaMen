@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 server.py
    pause
    exit /b
)
where python >nul 2>nul
if %errorlevel% equ 0 (
    python server.py
    pause
    exit /b
)
echo Python not found. Install Python 3.10 or newer from https://www.python.org/downloads/
echo During installation select Add Python to PATH. Then run this file again.
pause
