# One unattended pass for the owner (2026-11-18): the #13 streak A/Bs, then the
# full sweep, every round with its render.json pushed to vis-windows. No input.
#     .\scripts\morning_round.ps1
# Windows PowerShell 5.1 syntax only.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$fix = Join-Path $repo "scripts\visual_fix_round.ps1"
$ab = @(
    @{ Round = 1550; Switches = "-look-sun-shadows=off" },
    @{ Round = 1551; Switches = "-aerial-perspective-scale=0" },
    @{ Round = 1552; Switches = "-fog-density=0" }
)
foreach ($t in $ab) {
    Write-Host "`n===== round $($t.Round): #13 with $($t.Switches)"
    & $fix -Round $t.Round -Scenes "13" -Prep auto -CompareWith 154 -Switches $t.Switches -KeepRender
    Write-Host "round $($t.Round) exit $LASTEXITCODE"
}
Write-Host "`n===== round 155: full sweep"
& $fix -Round 155 -Full -KeepRender
Write-Host "round 155 exit $LASTEXITCODE"
Write-Host "`nmorning_round done: results are on vis-windows (docs/visual/round_1550..1552, round_155)"
