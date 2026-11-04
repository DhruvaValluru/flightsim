# Dot-sourced by build_ue.ps1 and ue_preflight.ps1:  . "$PSScriptRoot\ue_engine.ps1"
#
# One place that knows which Unreal Engine this project is pinned to and
# where that engine is installed. There is NO directory scan: the engine is
# $env:UE_ROOT, else the pinned install path, and a different version is a
# named refusal (engine.version_mismatch), never a quiet fallback to
# whichever UE_* folder happens to be newest.
# Windows PowerShell 5.1 syntax only (no ternary, no null-coalescing).

# The pinned engine, "major.minor", read from the project file so PowerShell
# and Python (test_platform.py compares the two) cannot drift apart.
function Get-PinnedEngine {
    $uproject = Join-Path $PSScriptRoot "..\ue\FlightSim.uproject"
    if (-not (Test-Path $uproject)) {
        throw "engine.pin_unreadable: no project file at $uproject"
    }
    $project = Get-Content $uproject -Raw | ConvertFrom-Json
    $pin = $project.EngineAssociation
    if (-not $pin) {
        throw "engine.pin_unreadable: EngineAssociation is missing from $uproject"
    }
    return "$pin"
}

# -> object { Root; Found; Pinned }. Found is "Major.Minor.Patch" read from
# Engine\Build\Build.version, or $null when that file is not there.
function Resolve-PinnedEngine($repo) {
    $pin = Get-PinnedEngine
    $root = $env:UE_ROOT
    if (-not $root) { $root = "C:\Program Files\Epic Games\UE_$pin" }
    $found = $null
    $versionFile = Join-Path $root "Engine\Build\Build.version"
    if (Test-Path $versionFile) {
        $v = Get-Content $versionFile -Raw | ConvertFrom-Json
        $found = "$($v.MajorVersion).$($v.MinorVersion).$($v.PatchVersion)"
    }
    return New-Object psobject -Property @{ Root = $root; Found = $found; Pinned = $pin }
}

# -> $null when the engine's major.minor is the pin, else the refusal text.
# Only major.minor is compared: a patch hotfix of the pinned engine builds.
function Test-EngineVersion($engine) {
    if (-not $engine.Found) { return $null }
    $parts = $engine.Found.Split(".")
    $majorMinor = $parts[0] + "." + $parts[1]
    if ($majorMinor -ne $engine.Pinned) {
        return "engine.version_mismatch: found $($engine.Found), pinned $($engine.Pinned)"
    }
    return $null
}
