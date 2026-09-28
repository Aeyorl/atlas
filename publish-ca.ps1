param (
    [Parameter(Mandatory=$true, Position=0, HelpMessage="Contract address (CA)")]
    [string]$CA
)

$ErrorActionPreference = "Stop"

$caTrimmed = $CA.Trim()
if ([string]::IsNullOrWhiteSpace($caTrimmed)) {
    Write-Error "Please provide a valid contract address."
    exit 1
}

$repoRoot = $PSScriptRoot
$indexPath = Join-Path $repoRoot "web\index.html"

Write-Host "Updating web\index.html with CA: $caTrimmed..." -ForegroundColor Cyan

$content = [System.IO.File]::ReadAllText($indexPath, [System.Text.Encoding]::UTF8)

# Replace data-token-ca
$content = [System.Text.RegularExpressions.Regex]::Replace(
    $content,
    'data-token-ca="[^"]*"',
    "data-token-ca=`"$caTrimmed`""
)

# Replace code inner text
$content = [System.Text.RegularExpressions.Regex]::Replace(
    $content,
    '<code id="tokenCaValue">[^<]*</code>',
    "<code id=`"tokenCaValue`">$caTrimmed</code>"
)

# Remove 'hidden' attribute from hero-ca
$content = $content.Replace('<div class="hero-ca" hidden', '<div class="hero-ca"')

[System.IO.File]::WriteAllText($indexPath, $content, [System.Text.Encoding]::UTF8)

Write-Host "Committing and pushing to GitHub (fork main)..." -ForegroundColor Cyan
git add web/index.html web/landing.css web/landing.js
git commit -m "feat(web): publish official community token CA $caTrimmed"
git push fork main

Write-Host "Deploying live to Vercel production..." -ForegroundColor Cyan
Set-Location (Join-Path $repoRoot "web")
npx --yes vercel --prod --yes
Set-Location $repoRoot

Write-Host "`nSUCCESS! Official CA is now live on https://www.niveprotocol.xyz" -ForegroundColor Green
