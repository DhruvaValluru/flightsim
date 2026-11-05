# Phase 3 Windows precondition check. Run before the runner starts; the runner
# refuses to prove anything unless docs/phase3/machine.json is fresh (written by
# this script within the last 12 hours) and carries ok=true.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows_env_check.ps1
#
# Every precondition the last run lost time to is asserted here by name, so a
# bad machine fails in seconds with a line that says what to fix, not an hour
# into an engine build.
$ErrorActionPreference = "Stop"

# A native command's stderr under the Stop preference ends the script; run it
# with Continue and leave $LASTEXITCODE for the caller.
function Invoke-Quiet([scriptblock]$Command) {
  $saved = $ErrorActionPreference
  try { $ErrorActionPreference = "Continue"; & $Command 2>$null | Out-Null }
  finally { $ErrorActionPreference = $saved }
}

Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$fails = @()
$facts = [ordered]@{}
function Fail([string]$name, [string]$why) { $script:fails += "$name`: $why"; Write-Host "FAIL  $name`: $why" }
function Ok([string]$name, [string]$what) { Write-Host "OK    $name`: $what" }

# 1. the pinned engine, at UE_ROOT, at the pinned version
$tc = Get-Content toolchain.json -Raw | ConvertFrom-Json
$pin = "$($tc.engine.version).$($tc.engine.patch)"
$ueRoot = $env:UE_ROOT
if (-not $ueRoot) { Fail "engine.ue_root_unset" "set `$env:UE_ROOT to the UE $($tc.engine.version) install folder" }
elseif (-not (Test-Path (Join-Path $ueRoot "Engine\Build\Build.version"))) { Fail "engine.ue_root_missing" "$ueRoot has no Engine\Build\Build.version" }
else {
  $bv = Get-Content (Join-Path $ueRoot "Engine\Build\Build.version") -Raw | ConvertFrom-Json
  $have = "$($bv.MajorVersion).$($bv.MinorVersion).$($bv.PatchVersion)"
  $facts.engine = $have; $facts.changelist = $bv.Changelist
  if ($have -ne $pin) { Fail "engine.version_mismatch" "found $have at UE_ROOT, toolchain.json pins $pin" } else { Ok "engine" "$have cl $($bv.Changelist) at $ueRoot" }
}

# 2. the cache folder, writable
$cache = $env:FLIGHTSIM_CACHE
if (-not $cache) { Fail "cache.unset" "set `$env:FLIGHTSIM_CACHE to a folder outside the clone (for example C:\flightsim-cache)" }
else {
  try { New-Item -ItemType Directory -Force -Path $cache | Out-Null; $probe = Join-Path $cache ".write-probe"; Set-Content $probe "ok"; Remove-Item $probe; $facts.cache = $cache; Ok "cache" $cache }
  catch { Fail "cache.not_writable" "$cache`: $($_.Exception.Message)" }
}

# 3. the machine tag the event helper uses
if ($env:FLIGHTSIM_MACHINE -ne "windows") { Fail "machine.tag" "set `$env:FLIGHTSIM_MACHINE = `"windows`" (events would be logged as mac)" } else { Ok "machine" "windows" }

# 4. the venv and its interpreter, at the pinned Python
if (-not (Test-Path ".venv\Scripts\python.exe")) { Fail "venv.missing" "py -$($tc.python.Substring(0,4)) -m venv .venv; .venv\Scripts\pip install --require-hashes -r requirements.lock" }
else {
  $pv = & .venv\Scripts\python.exe -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
  $facts.python = $pv
  if ($pv -ne $tc.python) { Fail "venv.python_mismatch" "venv is $pv, toolchain.json pins $($tc.python)" } else { Ok "python" $pv }
  Invoke-Quiet { & .venv\Scripts\python.exe -c "import numpy, jsbsim" }
  if ($LASTEXITCODE -ne 0) { Fail "venv.imports" "numpy or jsbsim does not import; reinstall from requirements.lock" } else { Ok "venv" "numpy and jsbsim import" }
}

# 5. tools on PATH
foreach ($t in @("ffmpeg", "git")) { if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { Fail "tool.$t" "$t is not on PATH" } else { Ok "tool" $t } }

# 6. Smart App Control must be off (it blocked dotnet and the Cesium DLL on 5.7)
try {
  $sac = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy" -Name VerifiedAndReputablePolicyState -ErrorAction Stop).VerifiedAndReputablePolicyState
  $facts.smart_app_control = $sac
  if ($sac -ne 0) { Fail "host.smart_app_control" "state $sac (1 = on, 2 = evaluation); turn it off in Windows Security, App & browser control" } else { Ok "smart_app_control" "off" }
} catch { Ok "smart_app_control" "key absent (not enforced)" }

# 7. a tiles credential (the repo fallback counts, but say which)
if ($env:GOOGLE_MAPS_API_KEY) { $facts.tiles = "GOOGLE_MAPS_API_KEY"; Ok "tiles" "GOOGLE_MAPS_API_KEY set" }
elseif ($env:CESIUM_ION_TOKEN) { $facts.tiles = "CESIUM_ION_TOKEN"; Ok "tiles" "CESIUM_ION_TOKEN set" }
else { $facts.tiles = "repo fallback"; Ok "tiles" "no variable; the engine's built-in fallback token will be used" }

# 8. git: on the pipeline branch, nothing uncommitted, origin reachable
$branch = (git rev-parse --abbrev-ref HEAD).Trim(); $facts.branch = $branch
if ($branch -ne "phase-2-final") { Fail "git.branch" "on $branch, the pipeline runs on phase-2-final" } else { Ok "git" "branch $branch" }
$dirty = git status --porcelain | Where-Object { $_ -notmatch "^\?\? " }
if ($dirty) { Fail "git.dirty" "uncommitted changes: $(($dirty | Measure-Object).Count) files; commit or stash before proving" }
Invoke-Quiet { git ls-remote --exit-code origin phase-2-final }
if ($LASTEXITCODE -ne 0) { Fail "git.origin" "origin phase-2-final not reachable" }

# 9. the built game module the editor commandlets need
if (-not (Test-Path "ue\Binaries\Win64\UnrealEditor-FlightSim.dll")) { Ok "ue_binaries" "absent; the runner builds once (stamp stale)" } else { $facts.ue_binaries = "present"; Ok "ue_binaries" "present" }

# 10. power: warn only
try { $plan = (powercfg /getactivescheme); Ok "power" ($plan -replace "\s+", " ") } catch {}

$out = [ordered]@{ ok = ($fails.Count -eq 0); checked = (Get-Date).ToString("o"); fails = $fails; facts = $facts; engine_pin = $pin }
New-Item -ItemType Directory -Force -Path docs\phase3 | Out-Null
$out | ConvertTo-Json -Depth 4 | Set-Content docs\phase3\machine.json -Encoding UTF8
if ($fails.Count -gt 0) { Write-Host "`n$($fails.Count) precondition(s) failed; fix them and run again. Written docs\phase3\machine.json with ok=false."; exit 1 }
Write-Host "`nAll preconditions pass. Written docs\phase3\machine.json."
exit 0
