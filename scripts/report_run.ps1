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

# Native git with $ErrorActionPreference dropped for the duration of the
# call. Under "Stop", Windows PowerShell 5.1 turns a REDIRECTED stderr
# line from a native command into a terminating NativeCommandError --
# the quirk setup.ps1 and deploy_windows.ps1 already carry a wrapper
# for, and which this script was written without.
#
# git writes to stderr as a matter of routine: `rev-parse` on a branch
# that does not exist yet, and `push` on every success. Measured on the
# first -Push run ever made: the report was written, then
#
#     git.exe : fatal: ambiguous argument 'refs/heads/run-reports':
#     unknown revision or path not in the working tree
#
# killed the script at the line whose whole job was to ask whether that
# branch existed. Not redirecting at all is the fix: stderr goes to the
# console where it can be read, and nothing throws. Existence is asked
# with `show-ref --verify --quiet`, which says it in an exit code and
# prints nothing either way.
#
# Arguments go in as ONE array rather than as remaining arguments:
# PowerShell would try to bind a leading `--verify` as a parameter name
# of this function.
#
# The name is NOT `Git`, and the call target is a resolved path, not the
# word `git`. PowerShell resolves a command as alias, then FUNCTION, then
# cmdlet, then external program, and it does so case-insensitively -- so
# `function Git { & git ... }` does not call git at all. It calls itself,
# forever:
#
#     The script failed due to call depth overflow.
#     At scripts\report_run.ps1:59 char:11
#     +     try { & git -C $repo @GitArgs }
#
# It is slow before it is fatal, which is why the run before it was
# reported as taking too long rather than as failing -- a recursion
# thousands of frames deep, doing nothing, looking exactly like a push
# waiting on a credential. Resolving git.exe once, up front, also turns
# "git is not on PATH" into a named failure here instead of a confusing
# one later.
$gitExe = (Get-Command "git.exe" -CommandType Application `
    -ErrorAction SilentlyContinue | Select-Object -First 1)
if (-not $gitExe) {
    Write-Error "git is not on PATH; run scripts\deploy_windows.ps1 first."
    exit 1
}
$gitExe = $gitExe.Source

function Invoke-Git {
    param([string[]]$GitArgs)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $gitExe -C $repo @GitArgs }
    finally { $ErrorActionPreference = $old }
}

function Get-GitLine {
    param([string[]]$GitArgs)
    $out = Invoke-Git $GitArgs | Select-Object -First 1
    if ($null -eq $out) { return "" }
    return ([string]$out).Trim()
}

# Progress goes to the CONSOLE, not into the report: a script that
# prints nothing for a minute is indistinguishable from a hung one, and
# the first -Push run that took a while was reported as "taking way too
# long" with no way to say which phase was taking it.
function Step([string]$text) {
    Write-Host ("  ... {0}" -f $text) -ForegroundColor DarkGray
}

if (-not $Run) {
    Step "finding the newest run under runs\"
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
Say "revision:   $(Get-GitLine @('rev-parse', '--short', 'HEAD'))"
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
#
# From the TAIL first. `Select-String -Path` reads the whole file, and a
# continuous capture makes these logs grow with the frame count -- the
# commandlet logs per frame, so 221 frames per camera is a log an order
# of magnitude longer than the three-still runs this was written
# against, times one per pass. Since the code only ever kept the LAST
# ten matches, reading the last few thousand lines gives the same answer
# in constant time. A refusal that fired early would be missed, so when
# the tail carries nothing named the whole file is scanned once -- rare,
# and worth the wait when it happens.
$TAIL_LINES = 4000
$logs = @(Get-ChildItem $runPath -Recurse -Filter "*.log" -ErrorAction SilentlyContinue)
if ($logs.Count -gt 0) {
    Say "ENGINE LOGS"
    foreach ($log in $logs) {
        Step ("reading {0} ({1:N0} bytes)" -f $log.Name, $log.Length)
        $pattern = "LogFlightSim|Error:|Fatal|refus|Warning/Error Summary"
        $named = Get-Content $log.FullName -Tail $TAIL_LINES `
            -ErrorAction SilentlyContinue |
            Select-String -Pattern $pattern | Select-Object -Last 10
        $whence = "last $TAIL_LINES lines"
        if (-not $named) {
            Step "  nothing named near the end; scanning the whole file"
            $named = Select-String -Path $log.FullName -Pattern $pattern `
                -ErrorAction SilentlyContinue | Select-Object -Last 10
            $whence = "whole file"
        }
        Say ("  -- {0} ({1} bytes, {2})" -f
             $log.FullName.Substring($runPath.Length + 1), $log.Length, $whence)
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
    $blob = Get-GitLine @("hash-object", "-w", $reportPath)
    # --cacheinfo, NOT a line piped into `update-index --index-info`.
    # PowerShell terminates a piped string with CRLF, so the path
    # reached git carrying a trailing carriage return -- a control
    # character, which Windows git rejects as an invalid path. It does
    # not fail loudly: it prints
    #
    #     Ignoring path reports/e4f389accddd.txt
    #
    # and carries on to write an EMPTY tree, so the push would have
    # succeeded and delivered a commit with no report in it. Measured
    # on the first -Push run. Passing the entry as an argument keeps
    # PowerShell's line endings out of it entirely.
    Invoke-Git @("update-index", "--add",
          "--cacheinfo", "100644,$blob,reports/$name.txt") | Out-Null
    $tree = Get-GitLine @("write-tree")

    $message = "run report $name"
    Invoke-Git @("show-ref", "--verify", "--quiet", "refs/heads/$Branch") | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $parent = Get-GitLine @("rev-parse", "refs/heads/$Branch")
        $commit = Get-GitLine @("commit-tree", $tree, "-p", $parent, "-m", $message)
    } else {
        $commit = Get-GitLine @("commit-tree", $tree, "-m", $message)
    }
    Invoke-Git @("update-ref", "refs/heads/$Branch", $commit) | Out-Null
} finally {
    Remove-Item Env:\GIT_INDEX_FILE -ErrorAction SilentlyContinue
    Remove-Item $tempIndex -ErrorAction SilentlyContinue
}

# A push that WAITS is worse than a push that fails. `run-reports` has
# never existed on the remote, and a first push of a new branch is
# exactly when git reaches for a credential helper -- which, if it has
# nothing cached, sits there forever waiting on a terminal prompt or on
# a Credential Manager window that may open behind everything else. The
# script looks hung and the report, already written to disk, looks lost.
# These two make a missing credential an immediate, named failure.
$oldPrompt = $env:GIT_TERMINAL_PROMPT
$oldInteractive = $env:GCM_INTERACTIVE
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "never"
try {
    for ($i = 1; $i -le 4; $i++) {
        Step "pushing to '$Branch' (attempt $i of 4)"
        Invoke-Git @("push", "-u", "origin", "${Branch}:${Branch}") | Out-Host
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "pushed to '$Branch' as reports/$name.txt -- nothing to paste."
            exit 0
        }
        Start-Sleep -Seconds ([math]::Pow(2, $i))
    }
    Write-Host ""
    Write-Host "could not push after 4 attempts. The report is already written:"
    Write-Host "  $reportPath"
    Write-Host "If git asked for credentials, this run refused to wait for them"
    Write-Host "(GIT_TERMINAL_PROMPT=0). Push the branch once by hand to store"
    Write-Host "them, then -Push works unattended from here on:"
    Write-Host "  git push -u origin ${Branch}:${Branch}"
    exit 1
} finally {
    if ($null -eq $oldPrompt) { Remove-Item Env:\GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue }
    else { $env:GIT_TERMINAL_PROMPT = $oldPrompt }
    if ($null -eq $oldInteractive) { Remove-Item Env:\GCM_INTERACTIVE -ErrorAction SilentlyContinue }
    else { $env:GCM_INTERACTIVE = $oldInteractive }
}
