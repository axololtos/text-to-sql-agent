@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Create it first:  uv venv --python 3.11  ^&^&  uv pip install -e .
    exit /b 1
)

if "%~1"=="" (
    set /p "QUESTION=Ask the database: "
    ".venv\Scripts\python.exe" agent.py "!QUESTION!"
) else (
    ".venv\Scripts\python.exe" agent.py %*
)
