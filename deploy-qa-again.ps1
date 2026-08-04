# Deploy QA-Again — Frontend to Cloudflare Pages + Backend to Fly.io
# Usage: .\deploy-qa-again.ps1
# Set PROJECT_DIR to your project path, or run from the project root.

param(
    [switch]$FrontendOnly,
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Get-Location }

Write-Host "🚀 Deploying QA-Again..." -ForegroundColor Green

# ─── Frontend (Cloudflare Pages via wrangler) ───
if (-not $BackendOnly) {
    Write-Host "`n📦 Building frontend..." -ForegroundColor Cyan
    Push-Location "$root\frontend"
    
    $env:VITE_API_BASE_URL = "https://qa-again-backend.fly.dev"
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    
    Write-Host "🌎 Deploying to Cloudflare Pages..." -ForegroundColor Cyan
    npx wrangler pages deploy dist --project-name=qa-again --branch=feature/hybrid-mvp
    if ($LASTEXITCODE -ne 0) { throw "Pages deploy failed" }
    
    Pop-Location
    Write-Host "✅ Frontend deployed! https://main.qa-again.pages.dev" -ForegroundColor Green
}

# ─── Backend (Fly.io) ───
if (-not $FrontendOnly) {
    Write-Host "`n🚀 Deploying backend to Fly.io..." -ForegroundColor Cyan
    Push-Location "$root\backend"
    
    fly deploy
    if ($LASTEXITCODE -ne 0) { throw "Backend deploy failed" }
    
    Pop-Location
    Write-Host "✅ Backend deployed! https://qa-again-backend.fly.dev" -ForegroundColor Green
}

Write-Host "`n🎉 QA-Again deploy complete!" -ForegroundColor Green
