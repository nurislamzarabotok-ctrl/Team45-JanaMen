#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 server.py
else
    echo 'Install Python 3.10+ from python.org, then run: sh start.sh'
    exit 1
fi
