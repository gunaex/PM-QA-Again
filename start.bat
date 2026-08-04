@echo off
setlocal

rem QA-Again local dev launcher: starts backend (FastAPI/uvicorn) and
rem frontend (Vite) each in their own window, installing dependencies on
rem first run if missing.
rem
rem No admin credentials are set here. On first run against an empty
rem database, the backend bootstraps one admin account automatically and
rem prints its one-time generated password to the BACKEND window's
rem console (see backend/app/seed.py) -- watch that window after first
rem launch. To choose your own credentials instead, set ADMIN_EMAIL and
rem ADMIN_PASSWORD as real environment variables in your own shell
rem BEFORE running this script (never hardcode them in this file or any
rem tracked file) -- they only take effect while the user database is
rem completely empty and are ignored once an account already exists.

set "ROOT=%~dp0"
set "ALLOWED_ORIGINS=http://localhost:5173"
set "ALLOW_LOCAL_DEV_ORIGINS=true"
set "JWT_SECRET_KEY=dev-local-secret-change-me"

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: "python" was not found on PATH. Install Python 3.11+ and re-run.
    exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
    echo ERROR: "npm" was not found on PATH. Install Node.js and re-run.
    exit /b 1
)

if not exist "%ROOT%backend\.venv" (
    echo Setting up backend virtual environment...
    python -m venv "%ROOT%backend\.venv"
    "%ROOT%backend\.venv\Scripts\pip" install -r "%ROOT%backend\requirements-dev.txt"
)

if not exist "%ROOT%frontend\node_modules" (
    echo Installing frontend dependencies...
    pushd "%ROOT%frontend"
    call npm install
    popd
)

echo Starting backend on http://127.0.0.1:8001 ...
echo (First run against an empty database: watch this window for a
echo  one-time generated admin password, unless you set ADMIN_EMAIL /
echo  ADMIN_PASSWORD yourself before running this script.)
start "QA-Again Backend" cmd /k "cd /d %ROOT%backend && set ALLOWED_ORIGINS=%ALLOWED_ORIGINS%&& set ALLOW_LOCAL_DEV_ORIGINS=%ALLOW_LOCAL_DEV_ORIGINS%&& set JWT_SECRET_KEY=%JWT_SECRET_KEY%&& .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001"

echo Starting frontend on http://localhost:5173 ...
start "QA-Again Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

timeout /t 3 >nul
start "" http://localhost:5173/login

endlocal
