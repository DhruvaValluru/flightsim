# Fly one scenario in the Unreal host with the renderer up, and write
# frames -- the render_ue_scenario.sh twin.
#
#     .\scripts\render_ue_scenario.ps1 <run-card.json> <frames-out-dir>
#
# The two flags that matter (same as the .sh, same reasons):
#   -AllowCommandletRendering   commandlets default to a null RHI; without
#                               this every capture is a blank frame that
#                               reports success.
#   -RenderOffScreen            no window needed. NOT the same as -nullrhi,
#                               which is the opposite.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($args.Count -ne 2) {
    Write-Error "usage: render_ue_scenario.ps1 <run-card.json> <frames-out-dir>"
    exit 2
}
$card = (Resolve-Path $args[0]).Path
New-Item -ItemType Directory -Force -Path $args[1] | Out-Null
$frames = (Resolve-Path $args[1]).Path

$editor = & (Join-Path $repo ".venv\Scripts\python.exe") -c "from core.util.platform import ue_editor_path; print(ue_editor_path())"
if (-not (Test-Path $editor)) { Write-Error "no editor at $editor (set UE_ROOT)"; exit 1 }
$bridge = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (-not (Test-Path $bridge)) { Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1 }

# Frames from an earlier run would be indistinguishable from this one's if
# the commandlet failed part way through.
Remove-Item (Join-Path $frames "frame_*.png") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $frames "render.json") -ErrorAction SilentlyContinue

& $editor (Join-Path $repo "ue\FlightSim.uproject") `
    -run=FlightSimBridge.FlightSimRender `
    "-scenario=$card" "-frames=$frames" `
    -unattended -nopause -nosplash -stdout -FullStdOutLogOutput `
    -RenderOffScreen -AllowCommandletRendering
if ($LASTEXITCODE -ne 0) { Write-Error "commandlet exited $LASTEXITCODE -- no frames"; exit $LASTEXITCODE }
if (-not (Test-Path (Join-Path $frames "render.json"))) {
    Write-Error "commandlet reported success but wrote no render.json"; exit 1
}
$count = (Get-ChildItem $frames -Filter "frame_*.png").Count
Write-Host "wrote $count frames and $frames\render.json"
