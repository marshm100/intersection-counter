@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0

REM Prefer the project venv (Python 3.12 — the version this project has always
REM run on; bare `py` resolves to 3.13 on the 2026-08-22 machine, which has no
REM project dependencies installed). Falls back to `py` so a machine that
REM installed deps globally still works.
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 5000 --reload
) else (
    py -m uvicorn backend.app:app --host 127.0.0.1 --port 5000 --reload
)
