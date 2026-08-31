# flightsim setup for Windows -- the setup.sh twin (venv + pip).
# Run from the repo root in PowerShell:  .\scripts\setup.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

Write-Host "flightsim setup (Windows)"

# py launcher if present, else python on PATH.
$python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" }
          else { "python" }

& $python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  .\.venv\Scripts\python.exe -m pytest        # suite (UE/mac tests skip, labeled)"
Write-Host "  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008"
Write-Host "  then open http://127.0.0.1:8008 and type a scenario."
Write-Host ""
Write-Host "Rendered video clips need UE 5.5 + Visual Studio 2022 and a"
Write-Host "locally built JSBSim library -- the full path is docs\WINDOWS.md."
Write-Host "Everything else -- compiler, physics, telemetry, terrain baking,"
Write-Host "the web app -- runs with just the setup above."
