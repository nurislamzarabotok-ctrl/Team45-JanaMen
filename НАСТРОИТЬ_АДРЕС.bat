@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 scripts/setup_public_url.py
pause
