# Build the Unreal host on Windows -- the build_ue.sh twin.
#
# Run from the repo root in PowerShell:  .\scripts\build_ue.ps1
# Uses the engine's own Build.bat (UnrealBuildTool finds Visual Studio
# 2022 itself; no toolchain override is needed the way DEVELOPER_DIR is
# on mac). Set UE_ROOT to point at a non-default install of the PINNED engine
# (ue\FlightSim.uproject EngineAssociation); another version is refused.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

. (Join-Path $PSScriptRoot "ue_engine.ps1")
$engine = Resolve-PinnedEngine $repo
$ueRoot = $engine.Root
$buildBat = Join-Path $ueRoot "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path $buildBat)) {
    throw ("no engine at $ueRoot (install UE $($engine.Pinned) or set UE_ROOT) -- see scripts\ue_preflight.ps1")
}
if (-not $engine.Found) {
    throw "engine.version_unreadable: no Engine\Build\Build.version under $ueRoot (pinned $($engine.Pinned))"
}
$mismatch = Test-EngineVersion $engine
if ($mismatch) { throw $mismatch }

function Get-PluginSourceHash {
    # Same bytes as core/util/platform.py plugin_source_hash: every file under
    # Source\ ordinal-sorted by "/"-separated relative path; CRLF folded to LF;
    # line = path + NUL + sha256(content) hex + LF; hash of the concatenation.
    param([string]$Repo)
    $root = (Resolve-Path (Join-Path $Repo "ue\Plugins\FlightSimBridge\Source")).Path.TrimEnd('\')
    $items = @()
    foreach ($f in Get-ChildItem -LiteralPath $root -Recurse -File) {
        $rel = $f.FullName.Substring($root.Length + 1).Replace('\', '/')
        $items += [pscustomobject]@{ Key = $rel; Path = $f.FullName }
    }
    $keys = [string[]]@($items | ForEach-Object { $_.Key })
    $paths = [string[]]@($items | ForEach-Object { $_.Path })
    [System.Array]::Sort($keys, $paths, [System.StringComparer]::Ordinal)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $ms = New-Object System.IO.MemoryStream
    for ($i = 0; $i -lt $keys.Length; $i++) {
        $raw = [System.IO.File]::ReadAllBytes($paths[$i])
        $norm = New-Object System.IO.MemoryStream
        for ($j = 0; $j -lt $raw.Length; $j++) {
            if ($raw[$j] -eq 13 -and ($j + 1) -lt $raw.Length -and $raw[$j + 1] -eq 10) { continue }
            $norm.WriteByte($raw[$j])
        }
        $hex = ([System.BitConverter]::ToString($sha.ComputeHash($norm.ToArray())) -replace '-', '').ToLower()
        $line = $utf8.GetBytes($keys[$i] + [char]0 + $hex + "`n")
        $ms.Write($line, 0, $line.Length)
    }
    return ([System.BitConverter]::ToString($sha.ComputeHash($ms.ToArray())) -replace '-', '').ToLower()
}

$target = if ($args.Count -ge 1) { $args[0] } else { "FlightSimEditor" }
$project = Join-Path $repo "ue\FlightSim.uproject"

Write-Host "building $target Win64 Development against UE $($engine.Found) at $ueRoot"
& $buildBat $target Win64 Development "-project=$project" -waitmutex
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
$stampDir = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries"
New-Item -ItemType Directory -Force -Path $stampDir | Out-Null
$stamp = [ordered]@{
    stamp_version = 1
    engine_version = [string]$engine.Found
    source_sha256 = (Get-PluginSourceHash $repo)
    built_utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
[System.IO.File]::WriteAllText((Join-Path $stampDir "build_stamp.json"), ($stamp | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "stamped $($stamp.source_sha256)"
Write-Host ""
Write-Host "built. Next: .\scripts\ue_preflight.ps1 to confirm, then render."
