@echo off
setlocal

rem QA-Again Runner launcher: starts the job-execution runner in watch
rem mode (claims and executes queued WorkflowRuns continuously, never
rem exits on its own). Double-click-run alternative to remembering
rem `npm run execute:watch` from a terminal.
rem
rem Requires runner\.env to already exist (copy runner\.env.example and
rem fill in BACKEND_BASE_URL / PROJECT_SLUG / RUNNER_TOKEN / TARGET_*
rem first -- see docs/hybrid/HYBRID_GUIDES.md's "Runner installation
rem guide"). This script does not create or edit .env for you.
rem
rem Leave this window open for as long as you want queued runs picked
rem up automatically. Closing it stops execution.

set "ROOT=%~dp0"

where npm >nul 2>nul
if errorlevel 1 (
    echo ERROR: "npm" was not found on PATH. Install Node.js and re-run.
    exit /b 1
)

if not exist "%ROOT%.env" (
    echo ERROR: runner\.env not found. Copy runner\.env.example to runner\.env
    echo and fill in BACKEND_BASE_URL / PROJECT_SLUG / RUNNER_TOKEN /
    echo TARGET_BASE_URL / TARGET_EMAIL / TARGET_PASSWORD first
    echo ^(see docs/hybrid/HYBRID_GUIDES.md^).
    exit /b 1
)

if not exist "%ROOT%node_modules" (
    echo Installing runner dependencies...
    pushd "%ROOT%"
    call npm install
    call npx playwright install chromium
    popd
)

echo Starting the QA-Again runner in watch mode -- it will keep claiming
echo and executing queued WorkflowRuns until you close this window.
echo A real headed Chromium window will open for each run it executes.
echo.

pushd "%ROOT%"
call npm run execute:watch
popd

endlocal
