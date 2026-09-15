# Run the backend test suite with coverage
# Equivalent to: make test-backend
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
& ".\venv\Scripts\Activate.ps1"
pytest
Pop-Location

