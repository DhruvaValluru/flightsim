# Fly one scenario in the Unreal host with the renderer up, and write frames
# -- ONE COMMANDLET PASS PER CAMERA.
#
#     .\scripts\render_ue_scenario.ps1 <run-card.json> <frames-out-dir>
#
# Camera Phase 2. A card carrying a `cameras` block is rendered once per
# camera (`-camera-index=N`), each pass writing into its own
# <frames-out-dir>\<camera_id>\ directory, which is exactly the layout
# capture_manifest.json names in every frame record's `file` field. Before
# this the wrapper ran a single pass and globbed a flat frame_*.png
# directory, so a two-camera manifest pointed at files that were never
# written and only the first camera was ever rendered.
#
# A card with no cameras block renders exactly as it always did: one pass,
# flat directory, byte-identical arguments.
#
# The output frame size and the field of view come from the card's own
# solved camera (the commandlet reads width_px / height_px /
# sensor_width_mm and the per-sample focal_length_mm), so -width= and
# -height= are NOT passed on the camera path: the manifest's intrinsics
# and the rendered pixels are the same numbers or the commandlet refuses.
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

$python = Join-Path $repo ".venv\Scripts\python.exe"
$editor = & $python -c "from core.util.platform import ue_editor_path; print(ue_editor_path())"
if (-not (Test-Path $editor)) { Write-Error "no editor at $editor (set UE_ROOT)"; exit 1 }
$bridge = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (-not (Test-Path $bridge)) { Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1 }

# The camera ids on the card, in the order the commandlet indexes them.
# An empty result means a card with no cameras block: the legacy single
# pass, unchanged.
$cameraJson = & $python -c @"
import json, sys
card = json.load(open(sys.argv[1], encoding='utf-8'))
print('\n'.join(str(c['camera_id']) for c in card.get('cameras', [])))
"@ $card
$cameraIds = @($cameraJson -split "`r?`n" | Where-Object { $_ -ne "" })

function Invoke-RenderPass {
    param([string]$OutDir, [string[]]$ExtraArgs)

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    # Frames from an earlier run would be indistinguishable from this one's
    # if the commandlet failed part way through.
    Remove-Item (Join-Path $OutDir "frame_*.png") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $OutDir "render.json") -ErrorAction SilentlyContinue

    $arguments = @(
        (Join-Path $repo "ue\FlightSim.uproject"),
        "-run=FlightSimBridge.FlightSimRender",
        "-scenario=$card", "-frames=$OutDir"
    ) + $ExtraArgs + @(
        "-unattended", "-nopause", "-nosplash", "-stdout",
        "-FullStdOutLogOutput", "-RenderOffScreen",
        "-AllowCommandletRendering"
    )
    & $editor @arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Error "commandlet exited $LASTEXITCODE -- no frames in $OutDir"
        exit $LASTEXITCODE
    }
    if (-not (Test-Path (Join-Path $OutDir "render.json"))) {
        Write-Error "commandlet reported success but wrote no render.json in $OutDir"
        exit 1
    }
    return (Get-ChildItem $OutDir -Filter "frame_*.png").Count
}

if ($cameraIds.Count -eq 0) {
    $count = Invoke-RenderPass -OutDir $frames -ExtraArgs @()
    Write-Host "wrote $count frames and $frames\render.json"
} else {
    $total = 0
    for ($i = 0; $i -lt $cameraIds.Count; $i++) {
        $id = $cameraIds[$i]
        $outDir = Join-Path $frames $id
        Write-Host "camera $($i + 1)/$($cameraIds.Count): $id -> $outDir"
        $count = Invoke-RenderPass -OutDir $outDir -ExtraArgs @("-camera-index=$i")
        Write-Host "  wrote $count frames"
        $total += $count
    }
    Write-Host "wrote $total frames across $($cameraIds.Count) camera(s) under $frames"
}
