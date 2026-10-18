@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 server.py --port 8017
pause
