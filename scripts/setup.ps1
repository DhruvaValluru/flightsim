# flightsim setup for Windows -- the setup.sh twin (venv + pip).
# Run from the repo root in PowerShell:  .\scripts\setup.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

Write-Host "flightsim setup (Windows)"

# requirements.lock is resolved for Python 3.12 (and numpy==2.0.2 has
# Windows wheels only up to 3.12), so any other version stops here
# rather than installing loose. Ask the py launcher for 3.12 first,
# else python on PATH.
#
# Probes run with $ErrorActionPreference dropped to Continue: under
# "Stop", PS 5.1 turns a REDIRECTED stderr line into a terminating error
# -- measured when the Microsoft Store's fake python.exe stub printed
# "Python was not found" and killed the script instead of reaching the
# install-instructions branch.
function Probe {
    param([string]$exe, [string[]]$probeArgs)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return & $exe @probeArgs 2>$null }
    catch { $global:LASTEXITCODE = 1; return $null }
    finally { $ErrorActionPreference = $old }
}

$pyExe = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $null = Probe "py" @("-3.12", "-c", "pass")
    if ($LASTEXITCODE -eq 0) { $pyExe = "py"; $pyArgs = @("-3.12") }
}
if (-not $pyExe) {
    $ver = Probe "python" @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    if ($LASTEXITCODE -ne 0 -or $ver -ne "3.12") {
        Write-Host "No Python 3.12 found: requirements.lock is pinned to"
        Write-Host "Python 3.12. Install it with:"
        Write-Host "  winget install -e --id Python.Python.3.12"
        Write-Host "then re-run this script -- or use the one-command deploy,"
        Write-Host "which installs it for you:  .\scripts\deploy_windows.ps1"
        exit 1
    }
    $pyExe = "python"
}

& $pyExe @pyArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  .\.venv\Scripts\python.exe -m pytest        # suite (UE/mac tests skip, labeled)"
Write-Host "  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008"
Write-Host "  then open http://127.0.0.1:8008 and type a scenario."
Write-Host ""
Write-Host "Camera capture demo (Windows is the supported render platform):"
Write-Host "  .\.venv\Scripts\python.exe -m flightsim.capture examples\cameras_multi.yaml --out runs\demo --card"
Write-Host "  .\.venv\Scripts\python.exe -m flightsim.verify runs\demo"
Write-Host ""
Write-Host "That writes runs\demo\capture_manifest.json -- every frame's"
Write-Host "camera pose, intrinsics and the aircraft state at that instant --"
Write-Host "and prints a pass/fail verification summary. To render the actual"
Write-Host "frames through those poses, install Unreal Engine 5.7 and build the"
Write-Host "bridge, then add --render:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\ue_preflight.ps1"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\build_ue.ps1"
Write-Host ""
Write-Host "Without the engine the capture, the manifest and every check that"
Write-Host "does not need pixels still run here; only the pixels are missing."
