@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0
py -m uvicorn backend.app:app --host 127.0.0.1 --port 5000
