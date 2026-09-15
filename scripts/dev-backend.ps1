# Start the FastAPI development server (reload enabled)
# Equivalent to: make dev-backend
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
& ".\venv\Scripts\Activate.ps1"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
Pop-Location

