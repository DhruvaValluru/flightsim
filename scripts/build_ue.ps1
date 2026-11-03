# Build the Unreal host on Windows -- the build_ue.sh twin.
#
# Run from the repo root in PowerShell:  .\scripts\build_ue.ps1
# Uses the engine's own Build.bat (UnrealBuildTool finds Visual Studio
# 2022 itself; no toolchain override is needed the way DEVELOPER_DIR is
# on mac). Set UE_ROOT to point at a non-default engine install.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# The pinned engine patch (Phase 3 A1, docs/TOOLCHAIN.md; the same value
# as UE_ENGINE_PATCH in core/util/platform.py -- tests/test_platform.py
# holds them equal). Only UE_ROOT or the pinned install path is used: the
# old "newest UE_5.* found" fallback is how the review's 5.5 machine built
# against the wrong engine (R1).
$pinned = "5.7.4"
$ueRoot = $env:UE_ROOT
if (-not $ueRoot) { $ueRoot = "C:\Program Files\Epic Games\UE_5.7" }
$buildBat = Join-Path $ueRoot "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path $buildBat)) {
    throw ("no engine at $ueRoot (install Unreal Engine $pinned, or set UE_ROOT) -- see scripts\ue_preflight.ps1")
}
$versionFile = Join-Path $ueRoot "Engine\Build\Build.version"
$found = "no readable Build.version"
if (Test-Path $versionFile) {
    $v = Get-Content $versionFile -Raw | ConvertFrom-Json
    $found = "$($v.MajorVersion).$($v.MinorVersion).$($v.PatchVersion)"
}
if ($found -ne $pinned) {
    Write-Host "REFUSED -- engine.version_mismatch: found $found, pinned $pinned (at $ueRoot)"
    Write-Host "Install Unreal Engine $pinned from the Epic Games Launcher, or point UE_ROOT at it."
    exit 2
}

# The interpreter that writes the build stamp (Phase 3 A4): the repo's
# venv when it exists (deploy_windows.ps1 / setup.ps1 make it), else PATH.
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$target = if ($args.Count -ge 1) { $args[0] } else { "FlightSimEditor" }
$project = Join-Path $repo "ue\FlightSim.uproject"

Write-Host "building $target Win64 Development with UE $found at $ueRoot"
& $buildBat $target Win64 Development "-project=$project" -waitmutex
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }

# The stamp every render checks (engine.binary_stale): the engine and a
# hash of the source this binary was built from. Written only after a
# clean build, so a failed build leaves the old stamp, which no longer
# matches the source, and the next render refuses.
# Only the editor target builds the DLL the render commandlet loads.
if ($target -eq "FlightSimEditor") {
    Push-Location $repo
    try { & $py -m core.util.build_stamp write --ue-root "$ueRoot" }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "build stamp not written ($LASTEXITCODE)" }
}
Write-Host ""
Write-Host "built. Next: .\scripts\ue_preflight.ps1 to confirm, then render."
