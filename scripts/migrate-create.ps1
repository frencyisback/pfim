# Generate a new Alembic migration using autogenerate
# Equivalent to: make migrate-create msg="description"
# Usage: .\scripts\migrate-create.ps1 "description of the change"
param(
    [Parameter(Mandatory = $true)]
    [string]$Message
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
& ".\venv\Scripts\Activate.ps1"
alembic revision --autogenerate -m "$Message"
Pop-Location

