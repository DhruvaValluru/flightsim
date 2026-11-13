# The stress ladder on the Windows render box: how much the laptop sustains.
#
#     .\scripts\stress_ladder.ps1                  # tier 0, three runs (the default; nothing else)
#     .\scripts\stress_ladder.ps1 -MaxTier 1       # opt in: climb to tier 1 if tier 0 held
#     .\scripts\stress_ladder.ps1 -MaxTier 3       # opt in: the whole ladder (tier 3 is meant to fail)
#
# Each run is one ordinary visual fix round (scripts\visual_fix_round.ps1)
# of scene 11 (the Matterhorn), with the tier's render switches as -Switches,
# -Compiler regex and its own -SpecDir (runs\stress_ladder\specs: the first
# run compiles scene 11 offline with the regex compiler and pins it, every
# later run replays that spec, and the visual rounds' pins are never touched),
# -NoPush, its own -Port, and -Prep none after the first run. Nothing reads a
# side file: a tier IS its -Switches string ($Tiers below).
#
# Around each run: typeperf samples GPU adapter memory (dedicated + shared),
# 3D engine utilisation and free RAM every second into
# runs\stress_ladder\<stamp>\tier<T>_run<R>_typeperf.csv. After it:
# scripts\stress_ladder.py judge reads the round's ROUND.json / summary.json
# and the run's render.log (device lost: DXGI_ERROR_DEVICE_HUNG / REMOVED /
# RESET, render.gpu_lost; the capture watchdog's render.capture_timeout, its
# exit 4; a stall kill; the round's own exit code) and writes tier<T>_run<R>.json.
# The round folder moves from docs\visual\round_<N> into the ladder folder.
# The ladder stops at the first run that did not survive and never climbs
# past it. At the end, stress_ladder.py summarise writes budget.json there
# and docs\hardware\hardware_budget_measured.json, which
# core\render\hardware_budget.py budget_from_file lays over the starting
# budget (measured = true only when tier 0 held all its runs).
#
# Round numbers: 9000 + 10 x tier + run (9001..9003 for tier 0), so the
# ladder never reuses a visual round's number. Commit nothing; the Claude
# session that ran it reports budget.json.
#
# Needs this script on claude/vibrant-gauss-olema4 (the round script checks
# that branch out; refused as ladder.not_on_round_branch otherwise).
# Exit: 0 tier 0 sustained, 1 it was not, 3 refused by name ("REFUSED <rule>: ...").
# A run whose round script threw (not exited) is judged with exit code 98.
# Windows PowerShell 5.1 syntax only.

param(
    # tiers above 0 are opt-in
    [ValidateRange(0, 3)][int]$MaxTier = 0,
    [ValidateRange(1, 10)][int]$Runs = 3,
    [int]$Scene = 11,
    [int]$RoundBase = 9000,
    # not the web app's 8008: a server already there would render without the switches
    [int]$Port = 8018,
    [int]$CooldownSeconds = 60,
    [ValidateSet("auto", "all", "none")][string]$Prep = "auto"
)

$ErrorActionPreference = "Continue"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
$round = Join-Path $repo "scripts\visual_fix_round.ps1"

function Refuse($rule, $words) {
    Write-Host "REFUSED ${rule}: $words"
    exit 3
}

# Each tier is the render switches the commandlet gets, nothing else
# (webapp\runs.py with_render_switches puts them on its command line ahead of
# the planned flags). Cvars ride -DPCVars=, comma separated. Left out on
# purpose: any cvar whose name ends in a word the commandlet parses as a
# value (r.SSR.Quality=, r.BloomQuality=, r.MotionBlurQuality= all end in
# "quality=", which FParse::Value could take for -quality=); the pytest
# checks every tier against the commandlet's FParse keys. Capture size is
# not a switch: a camera-carrying card takes width_px from the pinned spec.
$cv0 = "r.DynamicGlobalIlluminationMethod=0,r.ReflectionMethod=0,r.Shadow.Virtual.Enable=0,r.AntiAliasingMethod=1,r.ScreenPercentage=100,r.Shadow.MaxResolution=1024,r.Shadow.CSM.MaxCascades=2,r.AmbientOcclusionLevels=0,r.VolumetricCloud=0,r.VolumetricFog=0,r.MaxAnisotropy=4,r.Streaming.PoolSize=192,r.Streaming.LimitPoolSizeToVRAM=0"
$cv1 = "r.DynamicGlobalIlluminationMethod=0,r.ReflectionMethod=0,r.Shadow.Virtual.Enable=0,r.AntiAliasingMethod=2,r.ScreenPercentage=100,r.Shadow.MaxResolution=2048,r.Shadow.CSM.MaxCascades=3,r.AmbientOcclusionLevels=-1,r.VolumetricCloud=0,r.VolumetricFog=0,r.MaxAnisotropy=8,r.Streaming.PoolSize=320,r.Streaming.LimitPoolSizeToVRAM=0"
$cv2 = "r.DynamicGlobalIlluminationMethod=0,r.ReflectionMethod=0,r.Shadow.Virtual.Enable=0,r.AntiAliasingMethod=2,r.ScreenPercentage=100,r.Shadow.MaxResolution=2048,r.Shadow.CSM.MaxCascades=3,r.AmbientOcclusionLevels=-1,r.VolumetricCloud=1,r.VolumetricFog=0,r.MaxAnisotropy=8,r.Streaming.PoolSize=491,r.Streaming.LimitPoolSizeToVRAM=0"
$cv3 = "r.DynamicGlobalIlluminationMethod=0,r.ReflectionMethod=0,r.Shadow.Virtual.Enable=0,r.AntiAliasingMethod=2,r.ScreenPercentage=100,r.Shadow.MaxResolution=2048,r.Shadow.CSM.MaxCascades=4,r.AmbientOcclusionLevels=-1,r.VolumetricCloud=1,r.VolumetricFog=0,r.MaxAnisotropy=16,r.Streaming.PoolSize=640,r.Streaming.LimitPoolSizeToVRAM=0"
# index = tier
$Tiers = @(
    "-FlightSimStressTier=0 -DPCVars=$cv0",
    "-FlightSimStressTier=1 -DPCVars=$cv1",
    "-FlightSimStressTier=2 -DPCVars=$cv2",
    "-FlightSimStressTier=3 -DPCVars=$cv3"
)

# English counter names, one typeperf each: typeperf refuses its whole list
# when one path is unknown (an old driver has no GPU Adapter Memory; a
# localised Windows names them all differently). A missing counter leaves its
# CSV empty and the verdict's number null; the run is still judged.
$counters = [ordered]@{
    gpu_dedicated = '\GPU Adapter Memory(*)\Dedicated Usage'
    gpu_shared    = '\GPU Adapter Memory(*)\Shared Usage'
    gpu_3d        = '\GPU Engine(*engtype_3D)\Utilization Percentage'
    ram_free      = '\Memory\Available MBytes'
}

if (-not (Test-Path $py)) { Refuse "python.venv" "no $py -- run .\scripts\setup.ps1 first" }
if (-not (Test-Path $round)) { Refuse "ladder.no_round_script" "no $round" }
if (-not (Get-Command typeperf -ErrorAction SilentlyContinue)) { Refuse "ladder.no_typeperf" "typeperf.exe is not on PATH" }
# visual_fix_round.ps1 checks out and fast-forwards claude/vibrant-gauss-olema4
# on every run, so the ladder (and the round script's -Compiler / -SpecDir)
# must be on that branch, or the first run swaps them out from under it.
git fetch -q origin
git cat-file -e "origin/claude/vibrant-gauss-olema4:scripts/stress_ladder.py" 2>$null
if ($LASTEXITCODE -ne 0) { Refuse "ladder.not_on_round_branch" "scripts\stress_ladder.py is not on origin/claude/vibrant-gauss-olema4 yet; merge it there first" }
$busy = $false
try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/status" -TimeoutSec 3 | Out-Null; $busy = $true } catch { }
if ($busy) { Refuse "ladder.port_busy" "something already answers on port $Port; it would render without the tier's switches. Stop it or pass -Port" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$work = Join-Path $repo "runs\stress_ladder\$stamp"
$specs = Join-Path $repo "runs\stress_ladder\specs"
New-Item -ItemType Directory -Force $work, $specs | Out-Null
Write-Host "stress ladder: scene $Scene, tiers 0..$MaxTier, $Runs runs each -> $work"

$failed = $false
$first = $true
:ladder for ($tier = 0; $tier -le $MaxTier; $tier++) {
    for ($run = 1; $run -le $Runs; $run++) {
        $n = $RoundBase + 10 * $tier + $run
        $tag = "tier${tier}_run${run}"
        $switches = $Tiers[$tier]
        Write-Host "`n##### $tag (round $n): -Switches `"$switches`""
        $samplers = @()
        $csvs = @()
        foreach ($key in @($counters.Keys)) {
            $csv = Join-Path $work "${tag}_typeperf_$key.csv"
            $csvs += $csv
            # Start-Process joins the list with spaces and quotes nothing: quote by hand
            $tpArgs = @(('"' + $counters[$key] + '"'), "-si", "1", "-f", "CSV", "-o", ('"' + $csv + '"'), "-y")
            $samplers += Start-Process -FilePath "typeperf" -ArgumentList $tpArgs -PassThru -WindowStyle Hidden
        }
        $thisPrep = if ($first) { $Prep } else { "none" }
        $code = $null
        try {
            & $round -Round $n -Scenes "$Scene" -Switches $switches -Compiler regex -SpecDir $specs -Port $Port -Prep $thisPrep -NoPush
            $code = $LASTEXITCODE
        } catch {
            Write-Host "round script error: $($_.Exception.Message)"
            $code = 98
        } finally {
            foreach ($s in $samplers) { if ($s -and -not $s.HasExited) { Stop-Process -Id $s.Id -Force } }
        }
        if ($null -eq $code) { $code = 98 }
        $env:FLIGHTSIM_RENDER_SWITCHES = ""
        Set-Location $repo
        $first = $false
        Write-Host "round $n exit $code"
        $src = Join-Path $repo "docs\visual\round_$n"
        $dest = Join-Path $work "round_$n"
        if (Test-Path $src) {
            if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
            Move-Item $src $dest
        } else {
            New-Item -ItemType Directory -Force $dest | Out-Null
        }
        $judge = @("scripts\stress_ladder.py", "judge", "--tier", "$tier", "--run", "$run", "--round-dir", $dest, "--exit-code", "$code", "--out", (Join-Path $work "$tag.json"))
        foreach ($csv in $csvs) { $judge += @("--sampler", $csv) }
        & $py @judge
        if ($LASTEXITCODE -ne 0) { $failed = $true; break ladder }
        if ($CooldownSeconds -gt 0) { Start-Sleep -Seconds $CooldownSeconds }
    }
}

& $py scripts\stress_ladder.py summarise --dir $work --runs-per-tier $Runs
$measured = $LASTEXITCODE
Write-Host "`nladder folder: $work"
Write-Host "budget: $(Join-Path $work 'budget.json') (also docs\hardware\hardware_budget_measured.json)"
if ($measured -eq 0) { exit 0 }
exit 1
