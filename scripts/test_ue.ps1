# Run the plugin's C++ automation tests.
#
#     .\scripts\test_ue.ps1              # every FlightSim.* test
#     .\scripts\test_ue.ps1 CameraDirector   # one group
#
# The Python suite cannot reach the C++ tolerances -- the applied-vs-solved
# parity guards live inside AFlightSimCameraDirector and are decided by
# UE's own transform maths. Until this existed, "0.05 deg" was a number in
# a source file that nothing had ever driven, on either side of the line.
#
# -NullRHI because none of these render: they are arithmetic and refusal
# tests, and they should run on a machine with no GPU free. The editor
# still has to load the project, so this takes a minute even though the
# tests themselves are instant.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$filter = if ($args.Count -ge 1) { "FlightSim.$($args[0])" } else { "FlightSim" }

$python = Join-Path $repo ".venv\Scripts\python.exe"
$editor = & $python -c "from core.util.platform import ue_editor_path; print(ue_editor_path())"
if (-not (Test-Path $editor)) { Write-Error "no editor at $editor (set UE_ROOT)"; exit 1 }
$cmd = Join-Path (Split-Path $editor) "UnrealEditor-Cmd.exe"
if (-not (Test-Path $cmd)) { $cmd = $editor }
$bridge = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (-not (Test-Path $bridge)) { Write-Error "the bridge is not built -- run scripts\build_ue.ps1"; exit 1 }

$log = Join-Path $repo "ue_tests.log"
& $cmd (Join-Path $repo "ue\FlightSim.uproject") `
    "-ExecCmds=Automation RunTests $filter; Quit" `
    "-TestExit=Automation Test Queue Empty" `
    -unattended -nopause -nosplash -stdout -FullStdOutLogOutput -NullRHI `
    2>&1 | Tee-Object -FilePath $log | Out-Null

# The editor exits 0 whether the tests passed or not, so the verdict has
# to come out of the log. A runner that reported the editor's exit code
# would be a green light with nothing behind it.
$results = Select-String -Path $log -Pattern "LogAutomationController: (Test Completed|.*Result=)" |
    ForEach-Object { $_.Line }
$failed = Select-String -Path $log -Pattern "Automation Test Failed|Result=\{Fail\}|LogAutomationController: Error:"
$ran = Select-String -Path $log -Pattern "Test Completed\. Result=\{Success\}"

Write-Host ""
if ($ran) { $ran | ForEach-Object { Write-Host "  $($_.Line -replace '^.*LogAutomationController: *','')" } }
if ($failed) {
    Write-Host ""
    $failed | ForEach-Object { Write-Host "  $($_.Line)" }
    Write-Error "UE automation tests FAILED (full log: $log)"
    exit 1
}
if (-not $ran) {
    Write-Error "no automation test ran for filter '$filter' (full log: $log)"
    exit 1
}
Write-Host ""
Write-Host "$($ran.Count) UE automation test(s) passed."
