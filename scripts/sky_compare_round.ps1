# The owner's four-frame sky compare on the Windows render box (sky step 8).
#
#     .\scripts\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95
#     .\scripts\sky_compare_round.ps1 -Round 115 -Scene 13 -CompareWith 95 -Switches "-cloud-march=probe"
#     .\scripts\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95 -NoPush
#
# Brief step 8 (docs/visual/XPLANE_SKY_BRIEF.md; design docs/visual/XPLANE_SKY_DESIGN.md
# §10): ONE scene, the SAME camera, four fixed frames -- clear, scattered cumulus,
# broken stratocumulus, overcast -- plus a contact sheet against the old look, so
# the owner can judge on this laptop. Run from C:\Users\kanth\flightsim like
# scripts\visual_fix_round.ps1 (its header has the round rules).
#
# WHICH CODE THE FOUR FRAMES RENDER (the precondition). visual_fix_round.ps1 step 1
# checks out a branch and fast-forwards it FROM ORIGIN (by default
# phase-3-completed), so the laptop renders origin's copy of that branch,
# never the checkout you stand on. This script passes -Branch (default: the branch
# of the current checkout) through, and refuses by name (compare.wrong_branch) when
# origin/<branch> does not carry scripts/sky_contact_sheet.py and PLAN_CLOUD_SHAPES in
# core/scene/world_beauty.py: a host before sky step 2 (such as fbcbaa5d) does not
# parse -cloud-type=, ignores it silently, and would render four frames of the same
# look. So, before this command measures anything, claude/xplane-sky must be pushed
# (then run it from that checkout), or merged into phase-3-completed and
# pushed (then run it from that checkout, or pass -Branch phase-3-completed).
# What it does:
#
#  0. The branch check above; a refusal (compare.round_exists) when any of the four
#     round folders already exists under docs\visual or runs\vis-windows-wt\docs\visual
#     (a reused number would overwrite a round in vis-windows); a refusal
#     (compare.switch_dup) when -Switches itself carries -cloud-type=.
#  1. $env:FLIGHTSIM_SKY = "physical" when the shell has not set it (the physical
#     sky is opt-in, webapp\runs.py; the earlier rounds relied on the shell), and
#     records the value in the compare. Round M (the old look) may have rendered
#     without it; compare.json records M's commit and switches from its ROUND.json.
#  2. Four fix rounds, -Round N, N+1, N+2, N+3, each
#       .\scripts\visual_fix_round.ps1 -Round N+k -Scenes <S> -Switches "-cloud-type=<word> <extra>" -CompareWith <M> -Branch <B>
#     over the words clear, cumulus, stratocumulus, overcast (FlightSimClouds.cpp
#     Build parses -cloud-type=; another word refuses by name). One still each; the
#     pinned spec in runs\visual\specs\<NN>.json replays, so the camera does not
#     move between the four. Each round keeps its own docs\visual\round_<N+k>\
#     (frames, ROUND.json, metrics.json vs round M) and is pushed to vis-windows
#     by visual_fix_round.ps1 as usual. A round that refuses or fails stops the
#     set here, by name, with the word that failed.
#  3. python scripts\sky_contact_sheet.py --rounds N,N+1,N+2,N+3 --scene S --old M
#       --fallback-root runs\vis-windows-wt\docs\visual
#       -> docs\visual\sky_compare\round_<N>\sheet.jpg and compare.json
#     (row 1 the old frame, row 2 the four, each captioned with the word asked
#     and the shape render.json says was applied; MISMATCH when they differ,
#     "applied unknown" when the record names no shape, "-cloud-type= not parsed"
#     when the record does not carry the word asked). Round folders are looked
#     up under docs\visual, then runs\vis-windows-wt\docs\visual, the same two
#     places visual_fix_round.ps1 step 4b reads (rounds live on branch vis-windows).
#  4. Commits docs\visual\sky_compare\round_<N>\ to vis-windows through the same
#     separate worktree visual_fix_round.ps1 uses (runs\vis-windows-wt) and pushes
#     it; -NoPush skips this.
#
# Reading rule (compare.json): mismatches, unknown, switch_not_seen, no_record and
# missing ALL empty, and every tile's applied a shape word or "no layer".
# Nothing here measures anything until it has run: every frame is UNMEASURED
# until it exists. Exit: 0 done, 3 refused by name ("REFUSED <rule>: ..."),
# other = a step's own exit code. Windows PowerShell 5.1 syntax only.

param(
    # the FIRST of the four round numbers; the set is N, N+1, N+2, N+3. Steps 2, 3
    # and 5 reserved 98-105 for their own probes (VISUAL_FIDELITY_PLAN.md §8), so
    # the sky compares start at 110 (scene 3) and 115 (scene 13).
    [Parameter(Mandatory = $true)][int]$Round,
    # the scene (scripts\run_test_scenarios.py, 1-based): 3 = A320 over New York,
    # 600 m, 18 mm (the design's primary camera: bellies and rims against the sky);
    # 13 = the 747 cruise over the ocean at 10 km (tops from above)
    [int]$Scene = 3,
    # the previous round whose frame of the same scene is the "old look"
    [string]$CompareWith = "",
    # extra render switches every one of the four rounds carries (an A/B set is
    # its own -Round): e.g. "-cloud-march=probe"; never -cloud-type= (the words supply it)
    [string]$Switches = "",
    [switch]$NoPush,
    # the four words, in order; each is a -cloud-type= word the host accepts
    [string]$Words = "clear,cumulus,stratocumulus,overcast",
    # the branch visual_fix_round.ps1 checks out and fast-forwards from origin for
    # all four rounds; default the branch of the current checkout
    [string]$Branch = "",
    [int]$Port = 8008
)

# "Continue", not "Stop": under Stop, Windows PowerShell 5.1 turns any stderr
# line of a redirected native command into a terminating error (visual_fix_round.ps1).
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo
$py = Join-Path $repo ".venv\Scripts\python.exe"
$fixRound = Join-Path $PSScriptRoot "visual_fix_round.ps1"
$wt = Join-Path $repo "runs\vis-windows-wt"
$wtVisual = Join-Path $wt "docs\visual"

function Refuse($rule, $words) {
    Write-Host "REFUSED ${rule}: $words"
    exit 3
}

if (-not (Test-Path $py)) { Refuse "python.venv" "no $py -- run .\scripts\setup.ps1 first" }
if (-not (Test-Path $fixRound)) { Refuse "compare.no_fix_round" "no $fixRound" }
if ($Scene -lt 1) { Refuse "compare.no_scene" "name the scene (-Scene 3 or -Scene 13)" }
if ($CompareWith -notmatch '^(round_)?(\d+)$') { Refuse "compare.no_old" "name the previous round whose frame is the old look (-CompareWith 95)" }
$oldRound = [int]$Matches[2]
$wordList = @($Words -split '[,\s]+' | Where-Object { $_ -ne "" })
if ($wordList.Count -ne 4) { Refuse "compare.four_words" "four -cloud-type= words, got $($wordList.Count): $Words" }
$rounds = @(0..3 | ForEach-Object { $Round + $_ })
if ($rounds -contains $oldRound) { Refuse "compare.old_in_set" "-CompareWith $oldRound is one of the rounds $($rounds -join ', ')" }
# FParse::Value takes the FIRST -cloud-type= on the line, so a second one in -Switches
# would be silently ignored and the frame mislabelled: refuse instead.
if ($Switches -match '(^|\s)-cloud-type=') { Refuse "compare.switch_dup" "-Switches carries -cloud-type= ($Switches); the four words supply it" }

# 0a. a round number already used here or in vis-windows would be overwritten
# (visual_fix_round.ps1 step 6 removes the destination folder): refuse by name
foreach ($r in $rounds) {
    foreach ($cand in @((Join-Path $repo "docs\visual\round_$r"), (Join-Path $wtVisual "round_$r"))) {
        if (Test-Path $cand) { Refuse "compare.round_exists" "$cand exists; a reused round number would overwrite it in vis-windows: pick a free block (-Round)" }
    }
}

# 0b. the branch the four rounds render: visual_fix_round.ps1 checks it out and
# fast-forwards it FROM ORIGIN, so origin's copy must carry sky step 2's host
# (-cloud-type= parsed) and this step's sheet, or the four frames are one look.
if (-not $Branch) { $Branch = (git rev-parse --abbrev-ref HEAD).Trim() }
git fetch -q origin
if ($LASTEXITCODE -ne 0) { Refuse "git.fetch" "git fetch failed" }
git rev-parse -q --verify "origin/$Branch" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Refuse "compare.wrong_branch" "origin has no branch $Branch; push it, or merge claude/xplane-sky into phase-3-completed, push, and pass -Branch phase-3-completed" }
git cat-file -e "origin/${Branch}:scripts/sky_contact_sheet.py" 2>$null
if ($LASTEXITCODE -ne 0) { Refuse "compare.wrong_branch" "origin/$Branch has no scripts/sky_contact_sheet.py: sky step 8 is not on it; merge claude/xplane-sky into it and push first" }
$worldBeauty = @(git show "origin/${Branch}:core/scene/world_beauty.py" 2>$null)
if (-not ($worldBeauty | Select-String -Quiet -SimpleMatch "PLAN_CLOUD_SHAPES")) { Refuse "compare.wrong_branch" "origin/$Branch has no PLAN_CLOUD_SHAPES in core/scene/world_beauty.py: its host predates sky step 2, -cloud-type= would be ignored and the four frames would be one look; merge claude/xplane-sky into it and push first" }

# 1. the physical sky, stated rather than inherited
if (-not $env:FLIGHTSIM_SKY) { $env:FLIGHTSIM_SKY = "physical" }
Write-Host "FLIGHTSIM_SKY=$($env:FLIGHTSIM_SKY); branch $Branch; scene $Scene; rounds $($rounds -join ', ') vs round $oldRound"

# 2. the four rounds, one word each, same scene, same old round, same branch
for ($k = 0; $k -lt 4; $k++) {
    $word = $wordList[$k]
    $thisRound = $rounds[$k]
    $sw = "-cloud-type=$word"
    if ($Switches) { $sw = "$sw $Switches" }
    Write-Host "`n##### sky compare: round $thisRound, $sw"
    $fixArgs = @{ Round = $thisRound; Scenes = "$Scene"; Switches = $sw; CompareWith = "$oldRound"; Branch = $Branch; Port = $Port }
    if ($NoPush) { $fixArgs["NoPush"] = $true }
    & $fixRound @fixArgs
    # a .ps1 called with & sets $LASTEXITCODE from its exit; its exit 3 ends only itself
    $code = $LASTEXITCODE
    $done = $(if ($k -gt 0) { $rounds[0..($k - 1)] -join ', ' } else { 'none' })
    if ($code -ne 0) { Refuse "compare.round_failed" "round $thisRound ($sw) exit $code; rounds done: $done" }
    if (-not (Test-Path (Join-Path $repo "docs\visual\round_$thisRound"))) { Refuse "compare.no_round_folder" "round $thisRound wrote no docs\visual\round_$thisRound" }
}

# 3. the contact sheet against the old look
$out = Join-Path $repo "docs\visual\sky_compare\round_$Round"
$sheetArgs = @("scripts\sky_contact_sheet.py", "--rounds", ($rounds -join ","), "--scene", "$Scene", "--old", "$oldRound",
               "--out", $out, "--words", ($wordList -join ","))
# the old round usually lives only in the vis-windows worktree (step 4b of
# visual_fix_round.ps1 reads the same place second)
if (Test-Path $wtVisual) { $sheetArgs += @("--fallback-root", $wtVisual) }
# Windows PowerShell 5.1 drops an EMPTY string argument to a native command, which
# would leave "--switches" without its value: add each only when it has one.
if ($env:FLIGHTSIM_SKY) { $sheetArgs += @("--flightsim-sky", "$($env:FLIGHTSIM_SKY)") }
if ($Switches) { $sheetArgs += @("--switches", "$Switches") }
& $py @sheetArgs
if ($LASTEXITCODE -ne 0) { Refuse "compare.sheet" "sky_contact_sheet.py exit $LASTEXITCODE" }
if (-not (Test-Path (Join-Path $out "sheet.jpg"))) { Refuse "compare.no_sheet" "no sheet.jpg in $out" }
Write-Host "`nsky compare: $out"

# 4. vis-windows, through visual_fix_round.ps1's worktree
if ($NoPush) { Write-Host "-NoPush: $out"; exit 0 }
if (-not (Test-Path $wt)) {
    git worktree add -q $wt vis-windows 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { git worktree add -q -B vis-windows $wt origin/vis-windows }
}
$head = (git rev-parse --short=8 HEAD).Trim()
Push-Location $wt
try {
    git pull -q --ff-only origin vis-windows
    if ($LASTEXITCODE -ne 0) { Refuse "git.pull" "vis-windows worktree did not fast-forward from origin; resolve by hand" }
    $dest = Join-Path $wt "docs\visual\sky_compare\round_$Round"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item (Join-Path $out "*") $dest -Recurse
    git add "docs/visual/sky_compare/round_$Round"
    git commit -q -m "Sky compare round $Round on ${head} ($Branch): scene $Scene, rounds $($rounds -join ',') vs $oldRound [skip ci]"
    if ($LASTEXITCODE -ne 0) { Refuse "git.commit" "nothing committed for docs/visual/sky_compare/round_$Round" }
    git push -q origin vis-windows
    if ($LASTEXITCODE -ne 0) { Refuse "git.push" "push to vis-windows failed" }
    Write-Host "pushed vis-windows $((git rev-parse --short=8 HEAD).Trim()): docs/visual/sky_compare/round_$Round"
} finally {
    Pop-Location
}
exit 0
