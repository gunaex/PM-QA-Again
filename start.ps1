# QA-Again local dev launcher (PowerShell) -- starts backend
# (FastAPI/uvicorn) and frontend (Vite) each in their own window,
# installing dependencies on first run only if missing.
#
# No admin credentials are set here. On first run against an empty
# database, the backend bootstraps one admin account automatically and
# prints its one-time generated password to the BACKEND window's
# console (see backend/app/seed.py) -- watch that window after first
# launch. To choose your own credentials instead, set $env:ADMIN_EMAIL
# and $env:ADMIN_PASSWORD in your own shell BEFORE running this script
# (never hardcode them in this file or any tracked file) -- they only
# take effect while the user database is completely empty and are
# ignored once an account already exists.
# Never touches backend/data -- existing local projects/evidence are
# left alone.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python was not found on PATH. Install Python 3.11+ and re-run."
    exit 1
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm was not found on PATH. Install Node.js and re-run."
    exit 1
}

$env:ALLOWED_ORIGINS = "http://localhost:5173"
$env:ALLOW_LOCAL_DEV_ORIGINS = "true"
$env:JWT_SECRET_KEY = "dev-local-secret-change-me"

$backendVenv = Join-Path $root "backend\.venv"
if (-not (Test-Path $backendVenv)) {
    Write-Host "Setting up backend virtual environment..."
    python -m venv $backendVenv
    & "$backendVenv\Scripts\pip" install -r (Join-Path $root "backend\requirements-dev.txt")
}

$frontendModules = Join-Path $root "frontend\node_modules"
if (-not (Test-Path $frontendModules)) {
    Write-Host "Installing frontend dependencies..."
    Push-Location (Join-Path $root "frontend")
    npm install
    Pop-Location
}

Write-Host "Starting backend on http://127.0.0.1:8001 ..."
Write-Host "(First run against an empty database: watch this window for a one-time"
Write-Host " generated admin password, unless you set ADMIN_EMAIL / ADMIN_PASSWORD"
Write-Host " yourself before running this script.)"
Start-Process cmd -ArgumentList "/k", "cd /d `"$root\backend`" && set ALLOWED_ORIGINS=$($env:ALLOWED_ORIGINS)&& set ALLOW_LOCAL_DEV_ORIGINS=$($env:ALLOW_LOCAL_DEV_ORIGINS)&& set JWT_SECRET_KEY=$($env:JWT_SECRET_KEY)&& .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001"

Write-Host "Starting frontend on http://localhost:5173 ..."
Start-Process cmd -ArgumentList "/k", "cd /d `"$root\frontend`" && npm run dev"

Start-Sleep -Seconds 3
Start-Process "http://localhost:5173/login"

Write-Host ""
Write-Host "Backend:  http://127.0.0.1:8001"
Write-Host "Frontend: http://localhost:5173"
