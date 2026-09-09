# Fly, solve, render, verify. The single instructor command.
#
#     .\scripts\capture_windows.ps1                                  # the demo
#     .\scripts\capture_windows.ps1 examples\cameras_terrain.yaml runs\terrain
#     .\scripts\capture_windows.ps1 examples\cameras_multi.yaml runs\demo -SynthTerrain
#
# Everything below is `flightsim.capture --render` followed by
# `flightsim.verify`, which is exactly what the two-command form does.
# What this adds is that it STOPS at the first thing that went wrong and
# says which stage it was, and that it reads the verification's own
# verdict rather than reporting the exit code of the last thing it ran.
#
# It is not a wrapper that hides the commands. It prints each one before
# running it, so the two-command form stays the thing you learn.

param(
    [string]$Spec = "examples\cameras_multi.yaml",
    [string]$Out = "runs\demo",
    # Synthesise a ridge under the scenario's origin: deterministic from
    # its seed, no network, and the same Heightfield a Copernicus bake
    # produces. Without terrain the scene is sky and horizon only, which
    # is a real picture but not a real landscape.
    [switch]$SynthTerrain,
    # Render in the black void instead of the visual scene. What the
    # silhouette measurements want; not what a camera view looks like.
    [switch]$Void
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "no venv at $python -- run scripts\setup.ps1 first"; exit 1
}

$bridge = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (-not (Test-Path $bridge)) {
    Write-Host "the bridge is not built; building it first"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_ue.ps1")
    if ($LASTEXITCODE -ne 0) { Write-Error "the bridge did not build"; exit 1 }
}

$captureArgs = @("-m", "flightsim.capture", $Spec, "--out", $Out, "--render")
if ($SynthTerrain) { $captureArgs += "--synth-terrain" }
if ($Void) { $captureArgs += "--void" }

Write-Host ""
Write-Host "[1/2] $python $($captureArgs -join ' ')"
& $python @captureArgs
if ($LASTEXITCODE -ne 0) {
    # A named refusal is exit 2 and is a RESULT, not a crash: the spec
    # asked for something the scene cannot honour and the tool said which
    # clause. Distinguish it from a render that fell over.
    if ($LASTEXITCODE -eq 2) {
        Write-Host ""
        Write-Host "the capture refused by name (above). Nothing to verify."
    } else {
        Write-Host ""
        Write-Host "the capture failed at the render stage; the reason is in"
        Write-Host "  $Out\frames\<camera_id>\render.log"
    }
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/2] $python -m flightsim.verify $Out"
& $python -m flightsim.verify $Out
$verified = $LASTEXITCODE

Write-Host ""
if ($verified -eq 0) {
    $frames = (Get-ChildItem $Out -Recurse -Filter "frame_*.png").Count
    $overlays = (Get-ChildItem $Out -Recurse -Filter "overlay_*.png" -ErrorAction SilentlyContinue).Count
    Write-Host "PASSED. $frames rendered frames under $Out\frames, $overlays overlays under $Out\overlays."
    Write-Host "Look at the overlays first: circle = the manifest's projection,"
    Write-Host "cross = the engine's own. They should be one symbol per landmark."
} else {
    Write-Host "VERIFICATION FAILED -- read the FAIL lines above. The frames are"
    Write-Host "on disk either way; a failing check means the LABELS are wrong,"
    Write-Host "not that the render did not happen."
}
exit $verified
