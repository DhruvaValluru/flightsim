# flightsim setup for Windows -- the setup.sh twin (venv + pip).
# Run from the repo root in PowerShell:  .\scripts\setup.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

Write-Host "flightsim setup (Windows)"

# numpy==2.0.2 has Windows wheels only up to Python 3.12, so a default
# 3.13/3.14 install would try to build numpy from source and fail. Ask
# the py launcher for a covered version first, else python on PATH.
$pyExe = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("3.12", "3.11", "3.10")) {
        & py "-$v" -c "pass" 2>$null
        if ($LASTEXITCODE -eq 0) { $pyExe = "py"; $pyArgs = @("-$v"); break }
    }
}
if (-not $pyExe) {
    $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if (@("3.12", "3.11", "3.10", "3.9") -notcontains $ver) {
        Write-Host "No Python 3.10-3.12 found (numpy==2.0.2 ships no Windows"
        Write-Host "wheel past 3.12). Install one with:"
        Write-Host "  winget install -e --id Python.Python.3.12"
        Write-Host "then re-run this script -- or use the one-command deploy,"
        Write-Host "which installs it for you:  .\scripts\deploy_windows.ps1"
        exit 1
    }
    $pyExe = "python"
}

& $pyExe @pyArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  .\.venv\Scripts\python.exe -m pytest        # suite (UE/mac tests skip, labeled)"
Write-Host "  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008"
Write-Host "  then open http://127.0.0.1:8008 and type a scenario."
Write-Host ""
Write-Host "Rendered video clips currently require macOS (README 'Platform"
Write-Host "support'); everything else -- compiler, physics, telemetry,"
Write-Host "terrain baking, the web app -- runs here."
