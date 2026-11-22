# Run the frontend test suite (Vitest)
# Equivalent to: make test-frontend
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\frontend"
try {
    npm test
    $testExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $testExit

