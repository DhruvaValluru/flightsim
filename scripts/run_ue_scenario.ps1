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
# `if` is a STATEMENT in PowerShell, not an expression, so it cannot sit in
# an argument position -- `(Resolve-Path (if (...) {...} else {...}))` is a
# parse error, not a conditional. It read as valid to anyone used to a
# language with a ternary and stood here unrun: Gate 5 drove the .sh twin,
# and nothing on Windows called this script until the capture path started
# flying the host to solve over. The first invocation died on it.
$outDir = Split-Path -Parent $args[1]
if (-not $outDir) { $outDir = "." }
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}
$out = Join-Path (Resolve-Path $outDir).Path (Split-Path -Leaf $args[1])
$extra = @($args | Select-Object -Skip 2)

$editor = & (Join-Path $repo ".venv\Scripts\python.exe") -c "from core.util.platform import ue_editor_path; print(ue_editor_path())"
if (-not (Test-Path $editor)) { Write-Error "no editor at $editor (set UE_ROOT)"; exit 1 }
$bridge = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (-not (Test-Path $bridge)) { Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1 }

# A stale file from an earlier run would be indistinguishable from a fresh
# one if the commandlet failed before writing.
Remove-Item $out -ErrorAction SilentlyContinue

# Keep the engine's own output, for the reason render_ue_scenario.ps1 keeps
# its own: a named refusal from the commandlet is the one thing that says
# WHY a pass recorded nothing, and without this it scrolls past inside 20 MB
# of UE log and is gone.
$log = [System.IO.Path]::ChangeExtension($out, ".log")
& $editor (Join-Path $repo "ue\FlightSim.uproject") `
    -run=FlightSimBridge.FlightSimScenario `
    "-scenario=$card" "-telemetry=$out" `
    -unattended -nopause -nosplash -nullrhi -stdout -FullStdOutLogOutput `
    @extra 2>&1 | Tee-Object -FilePath $log | Out-Null
$code = $LASTEXITCODE

if ($code -ne 0 -or -not (Test-Path $out)) {
    Write-Host ""
    Write-Host "---- the commandlet's last words ($log) ----"
    $named = Select-String -Path $log -Pattern `
        "LogFlightSimScenario|LogFlightSimRender|scenario|telemetry|Error:|Fatal" |
        Select-Object -Last 25
    if ($named) { $named | ForEach-Object { Write-Host $_.Line } }
    else { Get-Content $log -Tail 25 | ForEach-Object { Write-Host $_ } }
    Write-Host "-------------------------------------------"
    if ($code -ne 0) {
        Write-Error "commandlet exited $code -- no telemetry"
        exit $code
    }
    Write-Error "commandlet reported success but wrote no $out"
    exit 1
}
Write-Host "wrote $out"
