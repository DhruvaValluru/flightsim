# Fly one scenario in the Unreal host, headlessly, and write its telemetry.
# The run_ue_scenario.sh twin -- identical commandlet and flags.
#
#     .\scripts\run_ue_scenario.ps1 <run-card.json> <telemetry-out.json> [extra commandlet flags]
#     e.g. -AllowNonParityEnvironment for a turbulence measurement run
#
# The run card is the spec, not a sentence and not a second set of numbers:
# the commandlet refuses any condition it cannot honour exactly rather than
# approximating it, so a card that runs here commands the same scenario the
# headless host ran. No compiler is involved -- this runs an already-built
# editor; building is scripts\build_ue.ps1.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if ($args.Count -lt 2) {
    Write-Error "usage: .\scripts\run_ue_scenario.ps1 <run-card.json> <telemetry-out.json> [extra commandlet flags]"
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
$OutDir = Split-Path -Parent $args[1]
if (-not $OutDir) { $OutDir = "." }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Out = Join-Path (Resolve-Path $OutDir).Path (Split-Path -Leaf $args[1])
$Extra = if ($args.Count -gt 2) { $args[2..($args.Count - 1)] } else { @() }

if (-not (Test-Path $Editor)) { Write-Error "no editor at $Editor (set UNREAL_EDITOR_EXE or UE_ROOT)"; exit 1 }
if (-not (Test-Path "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll")) {
    Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1
}

# A stale file from an earlier run would be indistinguishable from a fresh one
# if the commandlet failed before writing.
Remove-Item $Out -ErrorAction SilentlyContinue

$Project = Join-Path (Get-Location) "ue\FlightSim.uproject"
& $Editor $Project `
    -run=FlightSimBridge.FlightSimScenario `
    "-scenario=$Card" `
    "-telemetry=$Out" `
    -unattended -nopause -nosplash -nullrhi -stdout -FullStdOutLogOutput `
    @Extra
$Status = $LASTEXITCODE

if ($Status -ne 0) {
    Write-Error "commandlet exited $Status -- no telemetry"
    exit $Status
}
if (-not (Test-Path $Out)) {
    Write-Error "commandlet reported success but wrote no $Out"
    exit 1
}
Write-Host "wrote $Out"
