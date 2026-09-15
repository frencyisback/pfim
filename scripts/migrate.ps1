# Apply all pending Alembic migrations
# Equivalent to: make migrate
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
& ".\venv\Scripts\Activate.ps1"
alembic upgrade head
Pop-Location

