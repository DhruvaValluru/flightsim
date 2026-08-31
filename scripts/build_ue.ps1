# Build the Unreal host on Windows -- the build_ue.sh twin.
#
#     .\scripts\build_ue.ps1 [TargetName]
#
# Uses the engine's own Build.bat (UnrealBuildTool), the same entry point
# build_ue.sh uses on macOS via Build.sh. The Xcode/DEVELOPER_DIR logic has no
# Windows counterpart: the toolchain is Visual Studio 2022 with the MSVC C++
# toolset + Windows SDK ("Game development with C++" workload), which UBT
# discovers itself. The first build compiles engine plugin dependencies too
# and can take a long while; later builds are incremental.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Same resolution order as core/util/platform.py: UNREAL_EDITOR_EXE ->
# UE_ROOT -> the launcher's default install root.
if ($env:UNREAL_EDITOR_EXE -and (Test-Path $env:UNREAL_EDITOR_EXE)) {
    $UERoot = (Get-Item $env:UNREAL_EDITOR_EXE).Directory.Parent.Parent.Parent.FullName
} elseif ($env:UE_ROOT) {
    $UERoot = $env:UE_ROOT
} else {
    $UERoot = "C:\Program Files\Epic Games\UE_5.5"
}

$Target = if ($args.Count -ge 1) { $args[0] } else { "FlightSimEditor" }
$BuildBat = Join-Path $UERoot "Engine\Build\BatchFiles\Build.bat"
$Project = Join-Path (Get-Location) "ue\FlightSim.uproject"

if (-not (Test-Path $BuildBat)) {
    throw "no engine at $UERoot (set UNREAL_EDITOR_EXE or UE_ROOT) -- see scripts\ue_preflight.ps1"
}
if (-not (Test-Path $Project)) {
    throw "FlightSim.uproject not found at $Project (run from the repo root)"
}

# The Win64 JSBSim library is built locally, never shipped (docs\WINDOWS.md);
# without it the link fails late with a much less helpful message.
$Lib = "ue\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib\JSBSim.lib"
if (-not (Test-Path $Lib)) {
    throw "no $Lib -- run scripts\build_jsbsim_win64.ps1 first (the repo ships only the Mac dylib)"
}

Write-Host "building $Target Win64 Development with $BuildBat"
& $BuildBat $Target Win64 Development "-project=$Project" -waitmutex
if ($LASTEXITCODE -ne 0) {
    throw "build failed (exit $LASTEXITCODE)"
}
Write-Host "build OK"
