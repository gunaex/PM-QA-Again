# QA-Again Runner launcher (PowerShell) -- starts the job-execution
# runner in watch mode (claims and executes queued WorkflowRuns
# continuously, never exits on its own). Double-click-run alternative
# to remembering `npm run execute:watch` from a terminal.
#
# Requires runner/.env to already exist (copy runner/.env.example and
# fill in BACKEND_BASE_URL / PROJECT_SLUG / RUNNER_TOKEN / TARGET_*
# first -- see docs/hybrid/HYBRID_GUIDES.md's "Runner installation
# guide"). This script does not create or edit .env for you -- it can
# contain a real credential and must never be templated automatically.
#
# Leave this window open for as long as you want QueUed runs picked up
# automatically. Closing it (or Ctrl+C) stops execution -- any run
# already claimed and in progress is abandoned mid-step and will
# eventually self-report RUNNER_LOST once its lease expires server-side
# (see docs/hybrid/RECOVERY_RUNBOOK.md), never silently reported as a
# false PASS.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm was not found on PATH. Install Node.js and re-run."
    exit 1
}

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Write-Error "runner\.env not found. Copy runner\.env.example to runner\.env and fill in BACKEND_BASE_URL / PROJECT_SLUG / RUNNER_TOKEN / TARGET_BASE_URL / TARGET_EMAIL / TARGET_PASSWORD first (see docs/hybrid/HYBRID_GUIDES.md)."
    exit 1
}

$nodeModules = Join-Path $root "node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Host "Installing runner dependencies..."
    Push-Location $root
    npm install
    npx playwright install chromium
    Pop-Location
}

Write-Host "Starting the QA-Again runner in watch mode -- it will keep claiming"
Write-Host "and executing queued WorkflowRuns until you close this window."
Write-Host "A real headed Chromium window will open for each run it executes."
Write-Host ""

Push-Location $root
npm run execute:watch
Pop-Location
