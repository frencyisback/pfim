# Format and check code style (backend + frontend)
# Equivalent to: make lint
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
& ".\venv\Scripts\Activate.ps1"
# Include `migrations` alongside `app` and `tests`: migrations are executable
# Python code, and excluding them allowed their style to drift away from
# the rest of the backend.
black app tests migrations
isort app tests migrations
ruff check app tests migrations
Pop-Location

Push-Location "$root\frontend"
npm run lint
Pop-Location


