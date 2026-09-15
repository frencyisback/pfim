# Create a verified backup through the same service used by the API.
#
# This file intentionally contains no Authenticode signature block:
# any change invalidates the signature. Run scripts/sign-all.ps1 after
# reviewing the code to apply a new valid signature.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$python = Join-Path $backend "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "Virtual environment not found. Run scripts/setup.ps1 first."
    exit 1
}

Push-Location $backend
try {
    & $python -m app.cli.backup
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

