# Launch FlightSim.cmd -> this script (Phase 3 E6). Seven steps in order,
# stopping at the first failure with a named reason; every line goes to
# the window AND logs\launch.log; the last line is READY, or
# FAILED <step>: <reason>. No step prompts (the .cmd keeps the window open
# with cmd /k on a non-zero exit, so the reason stays readable).
#
#   1 install    scripts\deploy_windows.ps1 -NoLaunch -InstallDir <this folder>
#   2 preflight  scripts\ue_preflight.ps1 (toolchain.json pins)
#   3 build      scripts\launch_check.py build     -> scripts\build_ue.ps1
#   4 materials  scripts\launch_check.py materials -> ue_create_materials.py commandlet
#   5 aircraft   scripts\launch_check.py aircraft  -> scripts\import_aircraft.py <names>
#   6 bake       scripts\bake_terrain.py --places (D5; its lines are copied unchanged)
#   7 server     uvicorn on 127.0.0.1:8008, browser once it answers, READY
#
# The launcher sets no environment variable of the app's: tiles and
# weather stay exactly as the repo configures them. Windows PowerShell 5.1
# syntax only. Native exit codes are checked by hand ($LASTEXITCODE), so
# the preference stays Continue and stderr merges with 2>&1.
[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$logDir = Join-Path $repo "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$script:logPath = Join-Path $logDir "launch.log"
Set-Content -Path $script:logPath -Value @() -Encoding UTF8
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
$url = "http://127.0.0.1:8008/"

. (Join-Path $PSScriptRoot "ue_engine.ps1")

function Log($line) {
    $text = "$line"
    Add-Content -Path $script:logPath -Value $text -Encoding UTF8
    Write-Host $text
}

function Stop-With($step, $reason) {
    Log "FAILED ${step}: $reason"
    exit 1
}

function Invoke-Step($n, $name, $block) {
    Log "step $n/7 $name"
    & $block
}

# Runs one program, copying every line of its output (stderr merged) to
# the log, and returns the lines; the exit code is in $script:lastExit.
function Invoke-Logged($exe, [string[]]$arguments) {
    $script:lastExit = 0
    $lines = @(& $exe @arguments 2>&1 | ForEach-Object { $text = "$_"; Log $text; $text })
    $script:lastExit = $LASTEXITCODE
    return $lines
}

# Smart App Control blocks unsigned dlls (Cesium, UBT) on the laptop:
# Code Integrity events 3077/3033, GetLastError=4551. Reported, never fixed.
function Test-SmartAppControl($text) {
    return [bool]("$text" -match "Code Integrity.*(3077|3033)|GetLastError\s*=\s*4551|Smart App Control")
}

function Find-NamedReason($lines, $fallback) {
    foreach ($line in $lines) {
        $m = [regex]::Match("$line", "[a-z]+\.[a-z_]+(_mismatch|_stale|_unreadable|_failed|_missing)\b.*")
        if ($m.Success) { return $m.Value.Trim() }
    }
    foreach ($line in $lines) {
        if ("$line" -match "missing|not found|mismatch") { return "$fallback -- $("$line".Trim())" }
    }
    return $fallback
}

function Start-FlightSimServer {
    # A server already on 8008 is the OLD code (deploy_windows.ps1): stop it.
    try {
        $listening = @(Get-NetTCPConnection -LocalPort 8008 -State Listen -ErrorAction SilentlyContinue)
    } catch {
        $listening = @()
    }
    foreach ($conn in $listening) {
        $owner = $conn.OwningProcess
        if ($owner -and ($owner -ne $PID)) {
            Log "stopping the server already on port 8008 (pid $owner)"
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
        }
    }
    if ($listening.Count -gt 0) { Start-Sleep -Seconds 2 }
    Log "starting the web app on $url (its own window; close it to stop)"
    Start-Process -FilePath "powershell" -WorkingDirectory $repo `
        -ArgumentList "-NoExit", "-Command",
        "& '$venvPython' -m uvicorn webapp.server:app --port 8008"
    $up = $false
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            $up = $true
            break
        } catch { }
    }
    return $up
}

Invoke-Step 1 "install" {
    $out = Invoke-Logged "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        (Join-Path $PSScriptRoot "deploy_windows.ps1"), "-NoLaunch", "-InstallDir", $repo)
    if ($script:lastExit -ne 0) { Stop-With "install" (Find-NamedReason $out "install.lock_failed") }
    if (-not (Test-Path $venvPython)) { Stop-With "install" "install.venv_failed: no $venvPython" }
    # The native JSBSim library is built here, not committed: a fresh download
    # has its patched sources and no JSBSim.dll, and preflight refuses without it.
    $jsbsimDll = Join-Path $repo "ue\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib\JSBSim.dll"
    if (-not (Test-Path $jsbsimDll)) {
        $out = Invoke-Logged "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $PSScriptRoot "vendor_ue_plugin.ps1"))
        if ($script:lastExit -ne 0) { Stop-With "install" "install.jsbsim_vendor_failed: scriptsendor_ue_plugin.ps1 exited $($script:lastExit)" }
    }
}

Invoke-Step 2 "preflight" {
    $out = Invoke-Logged "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        (Join-Path $PSScriptRoot "ue_preflight.ps1"))
    if ($script:lastExit -ne 0) { Stop-With "preflight" (Find-NamedReason $out "toolchain.pin_unreadable") }
}

Invoke-Step 3 "build" {
    $null = Invoke-Logged $venvPython @("scripts\launch_check.py", "build")
    if ($script:lastExit -ne 0) {
        $out = Invoke-Logged "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $PSScriptRoot "build_ue.ps1"))
        if ($script:lastExit -ne 0) {
            if (Test-SmartAppControl ($out -join "`n")) { Stop-With "build" "host.smart_app_control" }
            Stop-With "build" "engine.binary_stale: build_ue.ps1 exited $script:lastExit"
        }
        Log "build built"
    }
}

Invoke-Step 4 "materials" {
    $null = Invoke-Logged $venvPython @("scripts\launch_check.py", "materials")
    if ($script:lastExit -ne 0) {
        $engine = Resolve-PinnedEngine $repo
        $editor = Join-Path $engine.Root "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
        if (-not (Test-Path $editor)) { Stop-With "materials" "materials.failed: no UnrealEditor-Cmd.exe under $($engine.Root)" }
        $uproject = Join-Path $repo "ue\FlightSim.uproject"
        $materialScript = Join-Path $repo "scripts\ue_create_materials.py"
        $out = Invoke-Logged $editor @($uproject, "-run=pythonscript", "-script=$materialScript",
            "-unattended", "-nopause", "-nosplash", "-stdout")
        $joined = $out -join "`n"
        if (Test-SmartAppControl $joined) { Stop-With "materials" "host.smart_app_control" }
        if (($script:lastExit -ne 0) -or ($joined -match "MATERIAL-FAILED")) {
            Stop-With "materials" "materials.failed: commandlet exited $script:lastExit"
        }
        $null = Invoke-Logged $venvPython @("scripts\launch_check.py", "materials", "--stamp")
        if ($script:lastExit -ne 0) { Stop-With "materials" "materials.failed: stamp not written" }
        Log "materials created"
    }
}

Invoke-Step 5 "aircraft" {
    $out = Invoke-Logged $venvPython @("scripts\launch_check.py", "aircraft")
    if ($script:lastExit -ne 0) {
        $m = [regex]::Match(($out -join "`n"), "aircraft stale \((.*)\)")
        if (-not $m.Success) { Stop-With "aircraft" "aircraft.import_failed: oracle printed no names" }
        $names = @($m.Groups[1].Value -split ",\s*" | Where-Object { $_ })
        $null = Invoke-Logged $venvPython (@("scripts\import_aircraft.py") + $names)
        if ($script:lastExit -ne 0) { Stop-With "aircraft" "aircraft.import_failed: import_aircraft.py exited $script:lastExit" }
        foreach ($name in $names) { Log "aircraft imported $name" }
    }
}

Invoke-Step 6 "bake" {
    $out = Invoke-Logged $venvPython @("scripts\bake_terrain.py", "--places")
    if ($script:lastExit -eq 2) { Stop-With "bake" "bake.usage $($out -join ' ')" }
    if ($script:lastExit -ne 0) {
        $failedLine = @($out | Where-Object { "$_" -match "^bake \S+ FAILED " }) | Select-Object -First 1
        if ($failedLine) { Stop-With "bake" "$failedLine" }
        Stop-With "bake" "bake.failed: bake_terrain.py exited $script:lastExit"
    }
}

Invoke-Step 7 "server" {
    $up = Start-FlightSimServer
    if (-not $up) { Stop-With "server" "server.not_answering: no HTTP answer on $url within 30 s" }
    if (-not $NoBrowser) { Start-Process $url }
    Log "READY"
}
exit 0
