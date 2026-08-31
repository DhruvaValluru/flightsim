# Build the Unreal host on Windows -- the build_ue.sh twin.
#
# Run from the repo root in PowerShell:  .\scripts\build_ue.ps1
# Uses the engine's own Build.bat (UnrealBuildTool finds Visual Studio
# 2022 itself; no toolchain override is needed the way DEVELOPER_DIR is
# on mac). Set UE_ROOT to point at a non-default engine install.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$ueRoot = $env:UE_ROOT
if (-not $ueRoot) {
    $ueRoot = "C:\Program Files\Epic Games\UE_5.5"
    if (-not (Test-Path $ueRoot)) {
        $found = Get-ChildItem "C:\Program Files\Epic Games" -Directory `
            -Filter "UE_5.*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($found) { $ueRoot = $found.FullName }
    }
}
$buildBat = Join-Path $ueRoot "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path $buildBat)) {
    throw ("no engine at $ueRoot (set UE_ROOT) -- see scripts\ue_preflight.ps1")
}

$target = if ($args.Count -ge 1) { $args[0] } else { "FlightSimEditor" }
$project = Join-Path $repo "ue\FlightSim.uproject"

Write-Host "building $target Win64 Development with $ueRoot"
& $buildBat $target Win64 Development "-project=$project" -waitmutex
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
Write-Host ""
Write-Host "built. Next: .\scripts\ue_preflight.ps1 to confirm, then render."
