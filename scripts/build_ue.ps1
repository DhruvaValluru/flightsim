# Build the Unreal host on Windows -- the build_ue.sh twin.
#
# Run from the repo root in PowerShell:  .\scripts\build_ue.ps1
# Uses the engine's own Build.bat (UnrealBuildTool finds Visual Studio
# 2022 itself; no toolchain override is needed the way DEVELOPER_DIR is
# on mac). Set UE_ROOT to point at a non-default install of the PINNED engine
# (ue\FlightSim.uproject EngineAssociation); another version is refused.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

. (Join-Path $PSScriptRoot "ue_engine.ps1")
$engine = Resolve-PinnedEngine $repo
$ueRoot = $engine.Root
$buildBat = Join-Path $ueRoot "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path $buildBat)) {
    throw ("no engine at $ueRoot (install UE $($engine.Pinned) or set UE_ROOT) -- see scripts\ue_preflight.ps1")
}
if (-not $engine.Found) {
    throw "engine.version_unreadable: no Engine\Build\Build.version under $ueRoot (pinned $($engine.Pinned))"
}
$mismatch = Test-EngineVersion $engine
if ($mismatch) { throw $mismatch }

$target = if ($args.Count -ge 1) { $args[0] } else { "FlightSimEditor" }
$project = Join-Path $repo "ue\FlightSim.uproject"

Write-Host "building $target Win64 Development against UE $($engine.Found) at $ueRoot"
& $buildBat $target Win64 Development "-project=$project" -waitmutex
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
Write-Host ""
Write-Host "built. Next: .\scripts\ue_preflight.ps1 to confirm, then render."
