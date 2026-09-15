# ONE-TIME setup: create a local code-signing certificate and trust it for
# your Windows user account. After this step, .ps1 scripts signed with
# .\scripts\sign-all.ps1 can run without PowerShell blocking them as
# "unsigned" or "downloaded from the internet".
#
# Usage (once only; no need to repeat for each patch):
#   .\scripts\setup-code-signing.ps1
#
# Note: this creates a SELF-SIGNED certificate, trusted only on your PC.
# It is not a publicly recognized certificate: it simply tells Windows
# "I trust scripts that I have signed myself".

$ErrorActionPreference = "Stop"

$existing = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq "CN=PFIM Local Dev" }

if ($existing) {
    Write-Host "Certificate 'PFIM Local Dev' already exists; reusing it." -ForegroundColor Yellow
    $cert = $existing[0]
} else {
    Write-Host "Creating a new code-signing certificate..." -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate `
        -Subject "CN=PFIM Local Dev" `
        -Type CodeSigningCert `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter (Get-Date).AddYears(5)
}

# Trust the certificate by copying it to your user's "Trusted Root" and
# "Trusted Publishers" stores, which Windows requires to accept
# self-signed scripts without warnings.
$rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
$rootStore.Open("ReadWrite")
$rootStore.Add($cert)
$rootStore.Close()

$publisherStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("TrustedPublisher", "CurrentUser")
$publisherStore.Open("ReadWrite")
$publisherStore.Add($cert)
$publisherStore.Close()

Write-Host "`nCertificate created and trusted." -ForegroundColor Green
Write-Host "Now run .\scripts\sign-all.ps1 to sign all scripts." -ForegroundColor Green

