# flightsim one-command Windows deploy.
#
# From any PowerShell window (no clone needed first):
#
#   irm https://raw.githubusercontent.com/DhruvaValluru/flightsim/master/scripts/deploy_windows.ps1 | iex
#
# or, from an existing clone:  .\scripts\deploy_windows.ps1
#
# What it does, in order: installs git and Python via winget only if
# missing, clones (or fast-forwards) the repo into ~\flightsim, builds
# the venv, installs the pinned requirements, starts the web app on
# http://127.0.0.1:8008 in its own window, and opens the browser.
# Re-running is safe: every step is skipped when already done.
#
# Parameters (only reachable when run as a file or via
# `& ([scriptblock]::Create((irm <url>))) -Branch x`):
#   -InstallDir  where to clone (default ~\flightsim; an existing clone
#                run from inside itself is reused in place)
#   -Branch      branch to check out (default master)
#   -NoLaunch    set up only; do not start the server or browser
#   -Reset       make the clone EXACTLY the remote branch (git reset
#                --hard origin/<branch>): local edits and local commits
#                on that branch are discarded. Use it when a re-run says
#                the pull was not a fast-forward and the page still shows
#                the old app.
#
# Re-running on an existing install updates it to the remote branch and
# RESTARTS the server: a uvicorn already on port 8008 keeps serving the
# code it loaded at start, so without the restart the page never shows
# what was just pulled (measured 2026-10-09: the route map was on the
# branch and absent from the page until the old server was stopped).

[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$Branch = "master",
    [switch]$NoLaunch,
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
$repoUrl = "https://github.com/DhruvaValluru/flightsim.git"

# numpy==2.0.2 is the narrowest pin: its Windows wheels stop at cp312,
# so a default 3.13/3.14 install would try to BUILD numpy and fail.
# Only these interpreter versions are accepted for the venv.
$acceptable = @("3.12", "3.11", "3.10")
$wingetPython = "Python.Python.3.12"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Refresh-Path {
    # winget installs land on the registry PATH, not this session's.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") +
                ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Require-Winget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw ("winget is not available, so missing tools cannot be " +
               "installed automatically. Install 'App Installer' from the " +
               "Microsoft Store (or install git and Python 3.12 yourself) " +
               "and re-run this script.")
    }
}

# --- git ---------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Require-Winget
    Step "git not found -- installing via winget (Git.Git)"
    winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git still not on PATH after install; open a new PowerShell window and re-run."
    }
}

# --- a Python with wheels for every pin --------------------------------
# Probe a native command with its stderr discarded SAFELY: under
# $ErrorActionPreference = "Stop", PS 5.1 turns a redirected stderr line
# into a terminating error -- measured when the Microsoft Store's fake
# python.exe stub printed "Python was not found" and killed the deploy.
function Probe {
    param([string]$exe, [string[]]$probeArgs)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return & $exe @probeArgs 2>$null }
    catch { $global:LASTEXITCODE = 1; return $null }
    finally { $ErrorActionPreference = $old }
}

# Returns @(exe, args...); splat everything after [0] so PS 5.1 and 7
# both pass the launcher's version flag through cleanly.
function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in $acceptable) {
            $null = Probe "py" @("-$v", "-c", "pass")
            if ($LASTEXITCODE -eq 0) { return , @("py", "-$v") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        # The Store alias stub also lives here: it fails the probe with a
        # nonzero exit, so requiring exit 0 rejects it.
        $ver = Probe "python" @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
        if ($LASTEXITCODE -eq 0 -and $acceptable -contains $ver) {
            return , @("python")
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Require-Winget
    Step "no Python 3.10-3.12 found -- installing 3.12 via winget ($wingetPython)"
    winget install -e --id $wingetPython --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $python = Find-Python
    if (-not $python) {
        throw "Python 3.12 still not found after install; open a new PowerShell window and re-run."
    }
}
$pyExe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)
Step ("using " + ($python -join " "))

# --- clone or update ---------------------------------------------------
if (-not $InstallDir) {
    # Run from inside a clone (deploy_windows.ps1 next to setup.ps1)?
    # Reuse it; otherwise default to ~\flightsim.
    $here = (Get-Location).Path
    if ((Test-Path (Join-Path $here ".git")) -and
        (Test-Path (Join-Path $here "scripts\deploy_windows.ps1"))) {
        $InstallDir = $here
    } else {
        $InstallDir = Join-Path $HOME "flightsim"
    }
}

if (Test-Path (Join-Path $InstallDir ".git")) {
    Step "updating existing clone at $InstallDir"
    git -C $InstallDir fetch origin $Branch
    git -C $InstallDir checkout $Branch
    if ($Reset) {
        Step "-Reset: making the clone exactly origin/$Branch (local edits discarded)"
        git -C $InstallDir reset --hard "origin/$Branch"
    } else {
        git -C $InstallDir pull --ff-only origin $Branch
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "    THE PULL WAS NOT A FAST-FORWARD: this clone has local edits or" -ForegroundColor Yellow
            Write-Host "    commits that origin/$Branch does not, so it was left as it is and" -ForegroundColor Yellow
            Write-Host "    the app below is NOT the remote branch. To serve exactly the remote:" -ForegroundColor Yellow
            Write-Host "      git -C $InstallDir reset --hard origin/$Branch" -ForegroundColor Yellow
            Write-Host "    or re-run this script with -Reset (local edits are discarded)." -ForegroundColor Yellow
            Write-Host ""
        }
    }
} else {
    Step "cloning $repoUrl -> $InstallDir"
    git clone --branch $Branch $repoUrl $InstallDir
}
$served = git -C $InstallDir log -1 --oneline
$behind = git -C $InstallDir rev-list --count "HEAD..origin/$Branch"
Step "this install is at: $served"
if ($behind -and ($behind -ne "0")) {
    Write-Host "    ($behind commit(s) on origin/$Branch are NOT in this install -- see above)" -ForegroundColor Yellow
}

# --- venv + pinned requirements ----------------------------------------
$venvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Step "creating venv"
    & $pyExe @pyArgs -m venv (Join-Path $InstallDir ".venv")
}

Step "installing pinned requirements (first run downloads ~200 MB of wheels)"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $InstallDir "requirements.txt")

Step "verifying the physics and server imports"
& $venvPython -c "import jsbsim, fastapi, uvicorn, rasterio, numpy"

if ($NoLaunch) {
    Write-Host ""
    Write-Host "Set up. Start it any time with:"
    Write-Host "  cd $InstallDir"
    Write-Host "  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008"
    return
}

# --- launch ------------------------------------------------------------
# A server already on 8008 is the OLD code: Python loaded webapp/server.py
# when it started and never re-reads it. Stop it, or the new one cannot
# bind and the browser keeps showing the app that was there before.
try {
    $listening = @(Get-NetTCPConnection -LocalPort 8008 -State Listen -ErrorAction SilentlyContinue)
} catch {
    $listening = @()
}
foreach ($conn in $listening) {
    $owner = $conn.OwningProcess
    if ($owner -and ($owner -ne $PID)) {
        Step "stopping the server already on port 8008 (pid $owner) so the updated code serves"
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    }
}
if ($listening.Count -gt 0) { Start-Sleep -Seconds 2 }

Step "starting the web app on http://127.0.0.1:8008 (its own window; close it to stop)"
# Wrapped in powershell -NoExit so a crashing server leaves its error ON
# SCREEN instead of a window that closes before anyone can read it.
Start-Process -FilePath "powershell" -WorkingDirectory $InstallDir `
    -ArgumentList "-NoExit", "-Command",
    "& '$venvPython' -m uvicorn webapp.server:app --port 8008"

$up = $false
foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:8008/" -UseBasicParsing -TimeoutSec 2
        $up = $true
        break
    } catch { }
}
if ($up) {
    Step "server is up, serving $served -- opening the browser"
    Start-Process "http://127.0.0.1:8008"
    Write-Host ""
    Write-Host "Type a scenario ('fly the c172p through a tornado over the prairie'),"
    Write-Host "review the compiled spec, and run. No API keys needed (README"
    Write-Host "'Quick start'). After Interpret, '+ draw the flight path' (beside the"
    Write-Host "camera buttons) opens the route map; hard-refresh (Ctrl+F5) if the"
    Write-Host "page was already open."
    Write-Host ""
    Write-Host "Camera capture, from this same install:"
    Write-Host "  cd $InstallDir"
    Write-Host "  .\.venv\Scripts\python.exe -m flightsim.capture examples\cameras_multi.yaml --out runs\demo --card"
    Write-Host "  .\.venv\Scripts\python.exe -m flightsim.verify runs\demo"
    Write-Host ""
    Write-Host "Windows is the supported platform for rendered frames. With"
    Write-Host "Unreal Engine 5.7 installed and scripts\build_ue.ps1 run, add"
    Write-Host "--render to the capture command and the frames come out per"
    Write-Host "camera under runs\demo\frames\. Without the engine everything"
    Write-Host "except the pixels still runs."
} else {
    throw ("the server did not answer on port 8008 within 30 s -- the " +
           "uvicorn window it opened stays up with the actual error; or run " +
           "it in THIS window to see it here:`n" +
           "  cd $InstallDir`n" +
           "  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008")
}
