# Everything about the last run, in one small file -- and optionally
# pushed, so nobody has to copy a console into a chat window.
#
#     .\scripts\report_run.ps1                 # newest run anywhere under runs\
#     .\scripts\report_run.ps1 -Push           # ...and push it for review
#     .\scripts\report_run.ps1 -Run runs\webapp\aa8ec29cb9ba
#
# Every failure on this branch has been diagnosed from a log: the
# PowerShell parse error, the split commandlet name, the scripted-card
# refusal, the schedule that outran the clip, the landmark sets that
# disagreed. Each one cost a round trip of "run it, find the log, paste
# the tail". This collects what those rounds actually needed -- the
# verification verdict with the detail of anything that is not a PASS,
# the named last words of every engine pass, what landed on disk, and
# the manifest's own account of which flight it describes -- into one
# file small enough to read at a glance.
#
# -Push puts it on the `run-reports` branch, which carries NOTHING else:
# reports are evidence about a run, not source, and they should never
# land in the branch's history. The working tree is untouched -- the
# push is built from a temporary index, so an in-progress edit is not
# committed and not stashed.

param(
    [string]$Run = "",
    [switch]$Push,
    [string]$Branch = "run-reports"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $Run) {
    $candidates = @(Get-ChildItem (Join-Path $repo "runs") -Recurse -Depth 2 `
        -Filter "capture_manifest.json" -ErrorAction SilentlyContinue)
    if ($candidates.Count -eq 0) {
        $candidates = @(Get-ChildItem (Join-Path $repo "runs") -Recurse -Depth 2 `
            -Filter "card.json" -ErrorAction SilentlyContinue)
    }
    if ($candidates.Count -eq 0) {
        Write-Error "no run found under $repo\runs -- give one with -Run"
        exit 1
    }
    $Run = ($candidates | Sort-Object LastWriteTime -Descending |
            Select-Object -First 1).Directory.FullName
}
$runPath = (Resolve-Path $Run).Path
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$name = Split-Path -Leaf $runPath

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text) { $lines.Add($text) }

Say "run report: $name"
Say "taken:      $stamp"
Say "path:       $runPath"
Say "revision:   $(& git -C $repo rev-parse --short HEAD 2>$null)"
Say ""

# -- what the manifest says it is --------------------------------------
$manifestPath = Join-Path $runPath "capture_manifest.json"
if (Test-Path $manifestPath) {
    $m = Get-Content $manifestPath -Raw | ConvertFrom-Json
    Say "MANIFEST"
    Say "  version       $($m.manifest_version)"
    Say "  solve_source  $($m.solve_source)"
    Say "  aircraft      $($m.aircraft)"
    Say "  scene         $($m.scene.key)"
    Say "  landmarks     $($m.landmarks.Count)"
    Say "  frames        $($m.frames.Count)"
    foreach ($c in $m.cameras) {
        Say "  camera        $($c.camera_id) ($($c.preset)), $($c.capture_count) image(s), $($c.schedule_basis)"
    }
    Say ""
} else {
    Say "MANIFEST      none -- this run stated no cameras, or it never got that far"
    Say ""
}

# -- the verdict, and the DETAIL of anything that is not a pass --------
$verifyPath = Join-Path $runPath "verify.json"
if (Test-Path $verifyPath) {
    $v = Get-Content $verifyPath -Raw | ConvertFrom-Json
    $pass = @($v.checks | Where-Object { $_.status -eq "PASS" }).Count
    $fail = @($v.checks | Where-Object { $_.status -eq "FAIL" }).Count
    $skip = @($v.checks | Where-Object { $_.status -eq "NOT RUN" }).Count
    Say "VERIFICATION  $pass passed, $fail failed, $skip not run"
    foreach ($c in $v.checks) {
        Say ("  [{0}] {1}" -f $c.status, $c.name)
    }
    # NOT RUN is not a pass, so its reason matters as much as a failure's.
    $interesting = @($v.checks | Where-Object { $_.status -ne "PASS" })
    if ($interesting.Count -gt 0) {
        Say ""
        Say "  why they did not pass:"
        foreach ($c in $interesting) {
            Say ("  -- {0} [{1}]" -f $c.name, $c.status)
            foreach ($line in ($c.detail -split "`n")) { Say "     $line" }
        }
    }
    Say ""
} else {
    Say "VERIFICATION  none -- the run did not reach it"
    Say ""
}

# -- what actually landed on disk --------------------------------------
Say "ON DISK"
foreach ($kind in @("frames", "overlays", "previews")) {
    $dir = Join-Path $runPath $kind
    if (-not (Test-Path $dir)) { continue }
    $perCamera = Get-ChildItem $dir -Directory -ErrorAction SilentlyContinue
    if ($perCamera) {
        foreach ($cam in $perCamera) {
            $n = @(Get-ChildItem $cam.FullName -Filter "*.png").Count
            Say ("  {0,-9} {1,-16} {2} png" -f $kind, $cam.Name, $n)
        }
    } else {
        $n = @(Get-ChildItem $dir -Filter "*.png").Count
        Say ("  {0,-9} {1,-16} {2} png" -f $kind, "(flat)", $n)
    }
}
foreach ($f in @("clip.mp4", "raw.mp4", "telemetry.json", "card.json",
                 "host_flight\host_telemetry.json")) {
    $path = Join-Path $runPath $f
    if (Test-Path $path) {
        Say ("  file      {0,-16} {1} bytes" -f $f, (Get-Item $path).Length)
    }
}
Say ""

# -- the engine's own last words, from every pass ----------------------
# The named lines only. A UE log is twenty megabytes of start-up around
# one sentence that says what went wrong.
$logs = @(Get-ChildItem $runPath -Recurse -Filter "*.log" -ErrorAction SilentlyContinue)
if ($logs.Count -gt 0) {
    Say "ENGINE LOGS"
    foreach ($log in $logs) {
        $named = Select-String -Path $log.FullName -Pattern `
            "LogFlightSim|Error:|Fatal|refus|Warning/Error Summary" `
            -ErrorAction SilentlyContinue | Select-Object -Last 10
        Say ("  -- {0} ({1} bytes)" -f
             $log.FullName.Substring($runPath.Length + 1), $log.Length)
        if ($named) { foreach ($n in $named) { Say "     $($n.Line.Trim())" } }
        else { Say "     (no named line; the pass said nothing it flags)" }
    }
    Say ""
}

$report = $lines -join "`r`n"
$reportPath = Join-Path $runPath "report.txt"
Set-Content -Path $reportPath -Value $report -Encoding UTF8
Write-Host $report
Write-Host ""
Write-Host "written to $reportPath"

if (-not $Push) {
    Write-Host "add -Push to put it on the '$Branch' branch for review."
    exit 0
}

# -- push it, without touching the working tree ------------------------
# A temporary index, so an in-progress edit is neither committed nor
# stashed. The report branch carries reports and nothing else.
$tempIndex = Join-Path $env:TEMP "flightsim-report-index-$PID"
$env:GIT_INDEX_FILE = $tempIndex
try {
    $blob = & git -C $repo hash-object -w $reportPath
    $entry = "100644 blob $blob`t" + "reports/$name.txt"
    $entry | & git -C $repo update-index --index-info
    $tree = & git -C $repo write-tree
    $parent = & git -C $repo rev-parse "refs/heads/$Branch" 2>$null
    if ($LASTEXITCODE -eq 0 -and $parent) {
        $commit = "run report $name" | & git -C $repo commit-tree $tree -p $parent
    } else {
        $commit = "run report $name" | & git -C $repo commit-tree $tree
    }
    & git -C $repo update-ref "refs/heads/$Branch" $commit
} finally {
    Remove-Item Env:\GIT_INDEX_FILE -ErrorAction SilentlyContinue
    Remove-Item $tempIndex -ErrorAction SilentlyContinue
}

for ($i = 1; $i -le 4; $i++) {
    & git -C $repo push -u origin "${Branch}:${Branch}" 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "pushed to '$Branch' as reports/$name.txt -- nothing to paste."
        exit 0
    }
    Start-Sleep -Seconds ([math]::Pow(2, $i))
}
Write-Error "could not push the report after 4 attempts"
exit 1
