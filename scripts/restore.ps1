# Crash-safe offline restore. Stop the backend first: the instance lock
# prevents concurrent execution with Uvicorn.
param(
    [Parameter(Mandatory = $true)]
    [string]$Filename,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ExpectedSha256,

    [string]$RequestId
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$python = Join-Path $backend "venv\Scripts\python.exe"
$expectedConfirmation = "RESTORE $Filename"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "Virtual environment not found. Run scripts/setup.ps1 first."
    exit 1
}

$confirmation = Read-Host "Type exactly '$expectedConfirmation'"
if ($confirmation -cne $expectedConfirmation) {
    Write-Error "Invalid confirmation. No files have been changed."
    exit 1
}

$arguments = @(
    "-m", "app.cli.restore", $Filename,
    "--expected-sha256", $ExpectedSha256,
    "--confirmation", $confirmation
)
if ($RequestId) {
    $arguments += @("--request-id", $RequestId)
}

Push-Location $backend
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

