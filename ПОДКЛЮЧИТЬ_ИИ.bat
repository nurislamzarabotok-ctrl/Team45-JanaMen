@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
 py -3 scripts/setup_ai.py
 pause
 exit /b
)
python scripts/setup_ai.py
pause
