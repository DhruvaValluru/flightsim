# One visual fix round on the Windows render box, sized to the fix.
#
#     .\scripts\visual_fix_round.ps1 -Round 6 -Scenes 11,15        # just these scenes, one still each
#     .\scripts\visual_fix_round.ps1 -Round 9 -Full                # all scenes + head shots vs the last head
#     .\scripts\visual_fix_round.ps1 -Round 6 -Scenes 1 -NoPush    # look locally, push nothing
#     .\scripts\visual_fix_round.ps1 -Round 8 -Scenes 6 -Switches "-look-ssgi=off"   # an A/B pass
#
# Owner, 2026-11-11: a fix round renders only the scenes the fix touches,
# one still each, and does the expensive prep only when its inputs changed.
# The full 14+ scene sweep (and the head comparison) runs once, at the end,
# with -Full. What it does, in order:
#
#  1. Fast-forwards claude/vibrant-gauss-olema4 (refuses git.not_fast_forward
#     rather than discarding local work).
#  2. Prep only what changed since the last prepared commit (runs\visual\prep_stamp.txt;
#     no stamp = all three):
#       build      ue\Plugins\*\Source, ue\Config, ue\FlightSim.uproject
#       materials  scripts\ue_create_materials.py, assets\shaders, assets\looks, core\scene\sky_hdri.py
#       aircraft   scripts\*aircraft*.py, assets\aircraft_config
#     -Prep all forces every step; -Prep none skips them.
#  3. Starts the web app (beauty, FLIGHTSIM_BEAUTY_POST=on unless already set),
#     runs scripts\run_test_scenarios.py --still --only <scenes> (--resume on a
#     memory stop, once), stops the app.
#  4. scripts\visual_round.py <Round> -> docs\visual\round_<Round>\ (each row
#     carries its wall seconds), plus ROUND.json: commit, scenes, prep steps
#     run and their seconds, outcomes.
#  5. -Full only: render_visual_sheet.ps1 -Step head<Round> and -Compare vs
#     -CompareWith (default: the newest runs\visual\head* before this one).
#  6. Commits docs\visual\round_<Round>\ to branch vis-windows through a
#     separate worktree (runs\vis-windows-wt), so the main checkout never
#     switches branch, and pushes it.
#
# Exit: 0 done, 3 refused by name (printed as "REFUSED <rule>: ..."), other = a
# step's own exit code. The Claude session that ran it messages flightsim-83
# with ROUND.json (docs\visual\FIX_ROUND_PROTOCOL.md).
# Windows PowerShell 5.1 syntax only.

param(
    [Parameter(Mandatory = $true)][int]$Round,
    # a string, split on commas: "powershell -File" turns an int[] "11,15" into 1115
    [string]$Scenes = "",
    [switch]$Full,
    [ValidateSet("auto", "all", "none")][string]$Prep = "auto",
    [string]$CompareWith = "",
    [switch]$NoPush,
    # render switches for this round only (FLIGHTSIM_RENDER_SWITCHES, e.g.
    # "-look-ssgi=off -deck-shadow=off"): an A/B pass is its own round number
    [string]$Switches = "",
    [int]$Port = 8008
)

# "Continue", not "Stop": under Stop, Windows PowerShell 5.1 turns any stderr
# line of a redirected native command (git, the editor) into a terminating
# error. Every native step's $LASTEXITCODE is checked by hand instead.
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
$branch = "claude/vibrant-gauss-olema4"
$ue = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.7" }
$ed = Join-Path $ue "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$proj = Join-Path $repo "ue\FlightSim.uproject"
$stampFile = Join-Path $repo "runs\visual\prep_stamp.txt"
$timings = [ordered]@{}

function Refuse($rule, $words) {
    Write-Host "REFUSED ${rule}: $words"
    exit 3
}

function Run-Step($name, [scriptblock]$body) {
    Write-Host "`n=== $name"
    $watch = [Diagnostics.Stopwatch]::StartNew()
    & $body
    $timings[$name] = [math]::Round($watch.Elapsed.TotalSeconds, 1)
    Write-Host "=== $name done in $($timings[$name]) s"
}

if (-not (Test-Path $py)) { Refuse "python.venv" "no $py -- run .\scripts\setup.ps1 first" }
$sceneList = @($Scenes -split '[,\s]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
if (-not $Full -and $sceneList.Count -eq 0) { Refuse "round.no_scenes" "name the scenes (-Scenes 11,15) or pass -Full" }

# 1. the branch, fast-forward only
git fetch -q origin
if ($LASTEXITCODE -ne 0) { Refuse "git.fetch" "git fetch failed" }
git checkout -q $branch
git merge -q --ff-only "origin/$branch"
if ($LASTEXITCODE -ne 0) { Refuse "git.not_fast_forward" "local $branch has commits origin does not; resolve by hand" }
$head = (git rev-parse --short=8 HEAD).Trim()
Write-Host "head $head"

# 2. prep, only what changed
$steps = @()
if ($Prep -eq "all") {
    $steps = @("build", "materials", "aircraft")
} elseif ($Prep -eq "auto") {
    $since = if (Test-Path $stampFile) { (Get-Content $stampFile -Raw).Trim() } else { "" }
    if (-not $since) {
        $steps = @("build", "materials", "aircraft")
    } else {
        git cat-file -e "$since^{commit}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            $steps = @("build", "materials", "aircraft")
        } else {
            $changed = @(git diff --name-only $since HEAD)
            if ($changed | Where-Object { $_ -match '^ue/Plugins/[^/]+/Source/|^ue/Config/|^ue/FlightSim\.uproject$' }) { $steps += "build" }
            if ($changed | Where-Object { $_ -match '^scripts/ue_create_materials\.py$|^assets/shaders/|^assets/looks/|^core/scene/sky_hdri\.py$' }) { $steps += "materials" }
            if ($changed | Where-Object { $_ -match '^scripts/[^/]*aircraft[^/]*\.py$|^assets/aircraft_config/' }) { $steps += "aircraft" }
        }
    }
}
Write-Host "prep: $(if ($steps.Count) { $steps -join ', ' } else { 'nothing changed' })"

if ($steps -contains "build") {
    Run-Step "build" {
        & (Join-Path $repo "scripts\build_ue.ps1")
        if ($LASTEXITCODE -ne 0) { Refuse "prep.build" "build_ue.ps1 exit $LASTEXITCODE" }
    }
}
if ($steps -contains "materials") {
    Run-Step "materials" {
        $log = Join-Path $repo "runs\visual\round_${Round}_materials.log"
        & $ed $proj -run=pythonscript "-script=$(Join-Path $repo 'scripts\ue_create_materials.py')" -unattended -nopause -nosplash -stdout -FullStdOutLogOutput *> $log
        if (Select-String -Path $log -Pattern "MATERIAL-FAILED" -Quiet) { Refuse "prep.materials" "MATERIAL-FAILED in $log" }
        & $py scripts\launch_check.py materials --stamp
    }
}
if ($steps -contains "aircraft") {
    Run-Step "aircraft" {
        & $py scripts\import_aircraft.py J11 c172p B747 A320
        if ($LASTEXITCODE -ne 0) { Refuse "prep.aircraft" "import_aircraft.py exit $LASTEXITCODE" }
    }
}
New-Item -ItemType Directory -Force (Split-Path $stampFile) | Out-Null
Set-Content -Path $stampFile -Value $head -Encoding ascii

# 3. the scenes, one still each, through the web app as on the page
if (-not $env:FLIGHTSIM_RENDER_QUALITY) { $env:FLIGHTSIM_RENDER_QUALITY = "beauty" }
if (-not $env:FLIGHTSIM_BEAUTY_POST) { $env:FLIGHTSIM_BEAUTY_POST = "on" }
$env:FLIGHTSIM_RENDER_SWITCHES = $Switches
$gallery = Join-Path $repo "runs\test_scenarios"
if (Test-Path $gallery) { Remove-Item -Recurse -Force $gallery }   # derived copies; runs\webapp keeps the runs
$serverLog = Join-Path $repo "runs\visual\round_${Round}_server.log"
$server = Start-Process -FilePath $py -ArgumentList @("-m", "uvicorn", "webapp.server:app", "--port", "$Port") `
    -WorkingDirectory $repo -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err" -PassThru -WindowStyle Hidden
try {
    $up = $false
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/status" -TimeoutSec 5 | Out-Null; $up = $true; break } catch { Start-Sleep 2 }
    }
    if (-not $up) { Refuse "webapp.not_up" "no answer on port $Port in 120 s; see $serverLog.err" }
    $batch = @("scripts\run_test_scenarios.py", "--still", "--server", "http://127.0.0.1:$Port")
    if (-not $Full) { $batch += @("--only") + ($sceneList | ForEach-Object { "$_" }) }
    Run-Step "scenes" {
        & $py @batch
        if ($LASTEXITCODE -eq 3) {
            Write-Host "batch stopped by name; one --resume"
            & $py @($batch + "--resume")
        }
    }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}

# 4. the round folder
& $py scripts\visual_round.py $Round
if ($LASTEXITCODE -ne 0) { Refuse "round.copy" "visual_round.py exit $LASTEXITCODE" }
$out = Join-Path $repo "docs\visual\round_$Round"

# 5. -Full: head shots against the last head
if ($Full) {
    if (-not $CompareWith) {
        $prev = Get-ChildItem (Join-Path $repo "runs\visual") -Directory -Filter "head*" |
            Where-Object { $_.Name -ne "head$Round" -and $_.Name -match '^head\d+$' } |
            Sort-Object { [int]($_.Name -replace 'head', '') } | Select-Object -Last 1
        if ($prev) { $CompareWith = $prev.Name }
    }
    Run-Step "head" { & (Join-Path $repo "scripts\render_visual_sheet.ps1") -Step "head$Round" }
    if ($CompareWith) {
        & (Join-Path $repo "scripts\render_visual_sheet.ps1") -Compare $CompareWith, "head$Round"
        Get-ChildItem (Join-Path $repo "runs\visual") -Filter "compare_*head$Round*.png" -Recurse |
            ForEach-Object { Copy-Item $_.FullName $out }
    }
}

$summary = @()
if (Test-Path (Join-Path $out "summary.json")) { $summary = Get-Content (Join-Path $out "summary.json") -Raw | ConvertFrom-Json }
$record = [ordered]@{
    round = $Round; commit = $head; full = [bool]$Full; scenes = $sceneList; switches = $Switches
    prep = $steps; seconds = $timings
    outcomes = @($summary | ForEach-Object { [ordered]@{ number = $_.number; outcome = $_.outcome; seconds = $_.seconds; why = $_.why } })
}
$record | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $out "ROUND.json") -Encoding utf8

# 6. vis-windows, through its own worktree
if ($NoPush) { Write-Host "`n-NoPush: $out"; exit 0 }
$wt = Join-Path $repo "runs\vis-windows-wt"
if (-not (Test-Path $wt)) {
    git worktree add -q $wt vis-windows 2>$null
    if ($LASTEXITCODE -ne 0) { git worktree add -q -B vis-windows $wt origin/vis-windows }
}
Push-Location $wt
try {
    git pull -q --ff-only origin vis-windows
    $dest = Join-Path $wt "docs\visual\round_$Round"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item (Join-Path $out "*") $dest -Recurse
    git add "docs/visual/round_$Round"
    $done = @($summary | Where-Object { $_.outcome -eq "done" }).Count
    git commit -q -m "Visual round $Round on ${head}: $done of $(@($summary).Count) rendered$(if ($Full) { ', full sweep' })$(if ($Switches) { ", switches $Switches" }) [skip ci]"
    git push -q origin vis-windows
    if ($LASTEXITCODE -ne 0) { Refuse "git.push" "push to vis-windows failed" }
    Write-Host "`npushed vis-windows $((git rev-parse --short=8 HEAD).Trim()): docs/visual/round_$Round"
} finally {
    Pop-Location
}
exit 0
