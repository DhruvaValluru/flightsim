# The coastal aircraft PBR gate: render the same shot with CoastalWeathering
# off and on, then measure the airframe pixels. Run on the Windows laptop:
#
#     powershell -ExecutionPolicy Bypass -File swarm\lanes\aircraft_exterior\pbr_materials\coastal\run_gate.ps1
#
# NEVER EXECUTED: written on the Mac. Exit 0 PASS, 1 FAIL, 2 REFUSED by
# measure_gate.py, 3 REFUSED here. See INTEGRATION.md, "The Windows gate".

param(
    [string]$Shot = "a",
    [string]$Ids = "1",
    [string]$RefStep = "coastal_pbr_ref",
    [string]$NewStep = "coastal_pbr_t0"
)

$ErrorActionPreference = "Stop"
$lane = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $lane "..\..\..\..\..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
$switch = "FLIGHTSIM_COASTAL_WEATHERING"

function Refuse([string]$why) {
    Write-Host "REFUSED coastal_pbr.gate: $why"
    exit 3
}

if (-not (Test-Path $python)) { Refuse "no $python -- run .\scripts\setup.ps1 first" }
$look = Join-Path $repo "scripts\aircraft_look.py"
if (-not (Select-String -Path $look -SimpleMatch $switch -Quiet)) {
    Refuse "$look does not read $switch (INTEGRATION.md change 6 is not merged); both renders would be the same scene"
}

function Render-Step([string]$step, [string]$value) {
    $dir = Join-Path $repo "runs\visual\$step"
    foreach ($name in @("$Shot.png", "${Shot}_mask.png")) {
        $old = Join-Path $dir $name
        if (Test-Path $old) { Remove-Item $old -Force }
    }
    Set-Item -Path "Env:$switch" -Value $value
    try {
        & (Join-Path $repo "scripts\render_visual_sheet.ps1") -Step $step -Shots $Shot
        $code = $LASTEXITCODE
    } finally {
        Remove-Item -Path "Env:$switch" -ErrorAction SilentlyContinue
    }
    if ($code -ne 0) { Refuse "render of $step ($switch=$value) exited $code" }
    $frame = Join-Path $dir "$Shot.png"
    if (-not (Test-Path $frame)) { Refuse "render of $step wrote no $frame (device lost or run failed: a FAIL of tier 0)" }
    return $frame
}

$before = Render-Step $RefStep "0"
$after = Render-Step $NewStep "1"
$mask = Join-Path $repo "runs\visual\$RefStep\${Shot}_mask.png"
if (-not (Test-Path $mask)) { Refuse "no $mask -- the run wrote no label mask (RENDER_RUNBOOK.md section 10)" }

& $python (Join-Path $lane "measure_gate.py") --before $before --after $after --mask $mask --ids $Ids
exit $LASTEXITCODE
