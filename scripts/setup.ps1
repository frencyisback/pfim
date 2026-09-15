# Complete setup (backend + frontend) - Windows PowerShell
# Equivalent to: make install
# Usage: .\scripts\setup.ps1   (from the pfim\ project root)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== Backend setup ===" -ForegroundColor Cyan
Push-Location "$root\backend"
python -m venv venv
$venvPython = Join-Path (Get-Location) "venv\Scripts\python.exe"
& $venvPython -m pip install --require-hashes -r pylock.toml
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created backend\.env from .env.example" -ForegroundColor Yellow
}
Pop-Location

Write-Host "=== Frontend setup ===" -ForegroundColor Cyan
Push-Location "$root\frontend"
npm ci
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created frontend\.env from .env.example" -ForegroundColor Yellow
}
Pop-Location

Write-Host "`nSetup complete. Start with:" -ForegroundColor Green
Write-Host "  .\scripts\dev-backend.ps1   (in one terminal)"
Write-Host "  .\scripts\dev-frontend.ps1  (in another terminal)"


