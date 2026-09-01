# Fly one scenario in the Unreal host, headlessly, and write its telemetry
# -- the run_ue_scenario.sh twin.
#
#     .\scripts\run_ue_scenario.ps1 <run-card.json> <telemetry-out.json> [extra flags]

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($args.Count -lt 2) {
    Write-Error "usage: run_ue_scenario.ps1 <run-card.json> <telemetry-out.json> [extra commandlet flags]"
    exit 2
}
$card = (Resolve-Path $args[0]).Path
$outDir = Split-Path -Parent $args[1]
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$out = Join-Path (Resolve-Path (if ($outDir) { $outDir } else { "." })).Path (Split-Path -Leaf $args[1])
$extra = @($args | Select-Object -Skip 2)

$editor = & (Join-Path $repo ".venv\Scripts\python.exe") -c "from core.util.platform import ue_editor_path; print(ue_editor_path())"
if (-not (Test-Path $editor)) { Write-Error "no editor at $editor (set UE_ROOT)"; exit 1 }
$bridge = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (-not (Test-Path $bridge)) { Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1 }

# A stale file from an earlier run would be indistinguishable from a fresh
# one if the commandlet failed before writing.
Remove-Item $out -ErrorAction SilentlyContinue

& $editor (Join-Path $repo "ue\FlightSim.uproject") `
    -run=FlightSimBridge.FlightSimScenario `
    "-scenario=$card" "-telemetry=$out" `
    -unattended -nopause -nosplash -nullrhi -stdout -FullStdOutLogOutput `
    @extra
if ($LASTEXITCODE -ne 0) { Write-Error "commandlet exited $LASTEXITCODE -- no telemetry"; exit $LASTEXITCODE }
if (-not (Test-Path $out)) { Write-Error "commandlet reported success but wrote no $out"; exit 1 }
Write-Host "wrote $out"
