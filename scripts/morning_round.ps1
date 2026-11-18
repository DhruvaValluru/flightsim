# One unattended pass for the owner (2026-11-18): the full sweep, every round with its render.json pushed to vis-windows. No input.
#     .\scripts\morning_round.ps1
# Windows PowerShell 5.1 syntax only.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$fix = Join-Path $repo "scripts\visual_fix_round.ps1"
Write-Host "`n===== round 155: full sweep"
& $fix -Round 155 -Full -KeepRender
Write-Host "round 155 exit $LASTEXITCODE"
Write-Host "`nmorning_round done: results are on vis-windows (docs/visual/round_155)"
