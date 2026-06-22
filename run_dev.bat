@echo off
:: Development mode — hot reload, full error tracebacks
setlocal
set APP_DIR=%~dp0
set FLASK_ENV=development

if not exist "%APP_DIR%venv\Scripts\python.exe" (
    python -m venv "%APP_DIR%venv"
    call "%APP_DIR%venv\Scripts\activate.bat"
    pip install -r "%APP_DIR%requirements.txt" --quiet
) else (
    call "%APP_DIR%venv\Scripts\activate.bat"
)
if not exist "%APP_DIR%data" mkdir "%APP_DIR%data"
cd /d "%APP_DIR%"
python wsgi.py
endlocal
