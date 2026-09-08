# Camera Phase 1, one command on Windows -- the verify_phase1.sh twin.
#
# Everything here runs on Windows exactly as it does on macOS and Linux.
# Rendered photographic frames need the Unreal host built here and are
# REFUSED BY NAME without it -- the designed outcome, not a failure. The
# manifests, the geometry previews and every check below are complete
# either way.
#
#   .\scripts\verify_phase1.ps1 [-Out runs\demo] [-Terrain <bake stem>]
param(
    [string]$Out = "runs\demo",
    [string]$Terrain = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No .venv here. Run .\scripts\setup.ps1 first."
    exit 1
}

Write-Host "== the camera test suite =="
# PowerShell does not expand globs for external programs, so the file
# list is built here -- and built by PATTERN, so a camera test added
# later is picked up instead of being silently skipped.
$cameraTests = Get-ChildItem -Path "tests" -Filter "test_camera_*.py" |
    ForEach-Object { $_.FullName }
if (-not $cameraTests) {
    Write-Host "FAIL: no tests/test_camera_*.py found"
    exit 1
}
& $python -m pytest @cameraTests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "== capture + verify: alignment, recovery, consistency =="
$demoArgs = @("--out", $Out)
if ($Terrain -ne "") { $demoArgs += @("--terrain", $Terrain) }
& $python -m flightsim.demo @demoArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "== the committed refusal example (expected: REFUSED by name) =="
# PowerShell 5.1 turns a redirected stderr line into a terminating error
# under "Stop"; the refusal writes to stdout, but the JSBSim banner does
# not, so the probe drops to Continue exactly like setup.ps1 does.
$old = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$log = & $python -m flightsim.capture examples\cameras_refusal.yaml `
    --out runs\refusal_check 2>&1 | Out-String
$code = $LASTEXITCODE
$ErrorActionPreference = $old
if ($code -eq 0) {
    Write-Host "FAIL: the refusal example did not refuse"
    exit 1
}
if ($log -notmatch "camera\.(terrain_clearance|scene_bounds|hazard_intersection)") {
    Write-Host "FAIL: refused, but not by a camera constraint"
    Write-Host $log
    exit 1
}
Write-Host "  refused by name, as documented"

Write-Host ""
Write-Host "Phase 1 verification complete."
