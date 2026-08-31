# Fly one scenario in the Unreal host with the renderer up, and write frames.
# The render_ue_scenario.sh twin -- identical commandlet and flags.
#
#     .\scripts\render_ue_scenario.ps1 <run-card.json> <frames-out-dir>
#
# The two flags that matter, and why the run is worthless without them:
#
#   -AllowCommandletRendering   commandlets come up with a null RHI by default.
#                               Without this every capture writes a blank frame
#                               and the run reports success.
#   -RenderOffScreen            no window, no display needed. Not the same
#                               thing as -nullrhi, which is the opposite.
#
# The commandlet checks for the renderer itself and refuses to write anything
# rather than produce files that look like evidence.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if ($args.Count -ne 2) {
    Write-Error "usage: .\scripts\render_ue_scenario.ps1 <run-card.json> <frames-out-dir>"
    exit 2
}

# Same resolution order as core/util/platform.py.
if ($env:UNREAL_EDITOR_EXE -and (Test-Path $env:UNREAL_EDITOR_EXE)) {
    $Editor = $env:UNREAL_EDITOR_EXE
} else {
    $UERoot = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.5" }
    $Editor = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
}

$Card = (Resolve-Path $args[0]).Path
New-Item -ItemType Directory -Force -Path $args[1] | Out-Null
$Out = (Resolve-Path $args[1]).Path

if (-not (Test-Path $Editor)) { Write-Error "no editor at $Editor (set UNREAL_EDITOR_EXE or UE_ROOT)"; exit 1 }
if (-not (Test-Path "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll")) {
    Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1
}

# Frames from an earlier run would be indistinguishable from this one's if the
# commandlet failed part way through.
Remove-Item (Join-Path $Out "frame_*.png") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Out "render.json") -ErrorAction SilentlyContinue

$Project = Join-Path (Get-Location) "ue\FlightSim.uproject"
& $Editor $Project `
    -run=FlightSimBridge.FlightSimRender `
    "-scenario=$Card" `
    "-frames=$Out" `
    -unattended -nopause -nosplash -stdout -FullStdOutLogOutput `
    -RenderOffScreen -AllowCommandletRendering
$Status = $LASTEXITCODE

if ($Status -ne 0) {
    Write-Error "commandlet exited $Status -- no frames"
    exit $Status
}
if (-not (Test-Path (Join-Path $Out "render.json"))) {
    Write-Error "commandlet reported success but wrote no $Out\render.json"
    exit 1
}
$Frames = (Get-ChildItem (Join-Path $Out "frame_*.png")).Count
Write-Host "wrote $Frames frames and $Out\render.json"
