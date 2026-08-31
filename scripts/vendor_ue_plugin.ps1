# Vendor the Win64 JSBSim library for the UE plugin -- the Windows twin of
# vendor_ue_plugin.sh, and deliberately SMALLER than it.
#
# The plugin's patched sources, headers and aircraft data are already
# committed (vendored on mac from the same v1.2.4 tag; see VENDORED.json,
# including the four recorded local patches). What Windows is missing is
# only the native library: Source\ThirdParty\JSBSim\Lib\JSBSim.dll + .lib,
# which the plugin's own Build.cs expects at exactly that path.
#
# §3.1 extends to how it is built: upstream ships JSBSimForUnreal.sln at
# the repo root for exactly this, so this script builds THAT with MSBuild
# rather than reimplementing its cmake/flags. The solution's own OutDir
# and post-build steps stage everything into its checkout's UnrealEngine
# plugin folder; only the two library files are copied here, so the
# committed patched sources are never overwritten.
#
# Run from the repo root in PowerShell:  .\scripts\vendor_ue_plugin.ps1
# Needs: git, Visual Studio 2022 with the C++ workload.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$jsbsimTag = "v1.2.4"
$upstream = "https://github.com/JSBSim-Team/jsbsim.git"
$work = Join-Path $env:TEMP "flightsim-vendor"
$src = Join-Path $work "jsbsim-$jsbsimTag"
$dest = Join-Path $repo "ue\Plugins\JSBSimFlightDynamicsModel"
$libDir = Join-Path $dest "Source\ThirdParty\JSBSim\Lib"

if (-not (Test-Path (Join-Path $dest "VENDORED.json"))) {
    throw ("the committed plugin is missing at $dest -- this script only " +
           "adds the Win64 library to the already-vendored plugin")
}

# --- MSBuild via vswhere (the supported way to find VS) -----------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found -- is Visual Studio 2022 installed?"
}
$msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild `
    -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
if (-not $msbuild) {
    throw ("no MSBuild found -- install the 'Desktop development with C++' " +
           "workload in Visual Studio 2022")
}
Write-Host "==> MSBuild: $msbuild"

# --- upstream checkout, pinned to the SAME tag the headless core runs ---
# §2.9: both hosts must run the same JSBSim or parity is untestable.
if (-not (Test-Path $src)) {
    Write-Host "==> fetching JSBSim $jsbsimTag"
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    git clone --depth 1 --branch $jsbsimTag $upstream $src
}
$commit = git -C $src rev-parse HEAD
$vendored = Get-Content (Join-Path $dest "VENDORED.json") -Raw | ConvertFrom-Json
if ($vendored.commit -ne $commit) {
    throw ("tag drift: committed plugin is from $($vendored.commit), " +
           "fresh $jsbsimTag checkout is $commit -- refusing to mix versions")
}

# --- build upstream's own solution --------------------------------------
# The .vcxproj pins PlatformToolset v142 (VS2019-era); v143 is VS2022's
# toolset and the override is the documented MSBuild knob for exactly
# this. WindowsTargetPlatformVersion=10.0 resolves to the newest
# installed SDK instead of the 2019-era one the project predates.
# The SOLUTION's configuration is named 1_Release (upstream numbered
# them; it maps to the project's Release|x64) -- plain "Release" fails
# with MSB4126.
Write-Host "==> building JSBSimForUnreal.sln (1_Release x64, v143 toolset)"
& $msbuild (Join-Path $src "JSBSimForUnreal.sln") `
    /p:Configuration=1_Release /p:Platform=x64 `
    /p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0 `
    /m /v:minimal
if ($LASTEXITCODE -ne 0) { throw "MSBuild failed ($LASTEXITCODE)" }

$builtLib = Join-Path $src "UnrealEngine\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib"
foreach ($f in "JSBSim.dll", "JSBSim.lib") {
    if (-not (Test-Path (Join-Path $builtLib $f))) {
        throw "$f was not produced at $builtLib"
    }
}

# --- copy ONLY the library; the committed patched sources stay ----------
New-Item -ItemType Directory -Force -Path $libDir | Out-Null
Copy-Item (Join-Path $builtLib "JSBSim.dll") $libDir -Force
Copy-Item (Join-Path $builtLib "JSBSim.lib") $libDir -Force
$dllSha = (Get-FileHash (Join-Path $libDir "JSBSim.dll") -Algorithm SHA256).Hash.ToLower()

# --- record it in VENDORED.json (via the venv python: honest JSON edit) --
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path $py) {
    & $py -c @"
import json, pathlib
p = pathlib.Path(r'$dest') / 'VENDORED.json'
d = json.loads(p.read_text(encoding='utf-8'))
d['library_win64'] = 'Source/ThirdParty/JSBSim/Lib/JSBSim.dll'
d['library_win64_sha256'] = '$dllSha'
d['library_win64_built_with'] = 'upstream JSBSimForUnreal.sln via MSBuild (not a reimplementation)'
p.write_text(json.dumps(d, indent=2) + '\n', encoding='utf-8')
print('VENDORED.json updated')
"@
} else {
    Write-Host "(no .venv yet -- VENDORED.json not updated; run scripts\setup.ps1 first)"
}

Write-Host ""
Write-Host "vendored Win64 library into $libDir"
Write-Host "  tag        $jsbsimTag @ $($commit.Substring(0,12))"
Write-Host "  dll sha256 $dllSha"
Write-Host ""
Write-Host "Next: .\scripts\build_ue.ps1"
