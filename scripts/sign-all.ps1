# Digitally sign all .ps1 scripts in scripts/ with the local certificate
# created by .\scripts\setup-code-signing.ps1.
#
# Run this script whenever a patch adds or modifies .ps1 files.
# You only need to sign them again; certificate setup does not need
# to be repeated.
#
# Usage:
#   .\scripts\sign-all.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq "CN=PFIM Local Dev" } | Select-Object -First 1

if (-not $cert) {
    Write-Host "No certificate found. First run:" -ForegroundColor Red
    Write-Host "  .\scripts\setup-code-signing.ps1"
    exit 1
}

# Unblock files (Mark of the Web) before signing: signing prevents FUTURE
# blocks, but previously downloaded files must be unblocked once to
# remove the remaining flag.
Get-ChildItem -Path "$root\scripts\*.ps1" | Unblock-File

$signed = 0
foreach ($file in Get-ChildItem -Path "$root\scripts\*.ps1") {
    if ($file.Name -eq "sign-all.ps1" -or $file.Name -eq "setup-code-signing.ps1") {
        # Sign these two as well, after processing the others
        continue
    }
    $result = Set-AuthenticodeSignature -FilePath $file.FullName -Certificate $cert
    Write-Host "$($file.Name): $($result.Status)"
    $signed++
}

# Finally, sign this script and the setup script
Set-AuthenticodeSignature -FilePath "$root\scripts\sign-all.ps1" -Certificate $cert | Out-Null
Set-AuthenticodeSignature -FilePath "$root\scripts\setup-code-signing.ps1" -Certificate $cert | Out-Null

Write-Host "`n$signed scripts signed successfully." -ForegroundColor Green
Write-Host "PowerShell should no longer block them." -ForegroundColor Green

