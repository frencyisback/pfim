# Start the Vite development server
# Equivalent to: make dev-frontend
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\frontend"
npm run dev
Pop-Location

