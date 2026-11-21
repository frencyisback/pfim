# Run the backend test suite with coverage
# Equivalent to: make test-backend
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
try {
    & ".\venv\Scripts\python.exe" -m pytest
    $testExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $testExit

