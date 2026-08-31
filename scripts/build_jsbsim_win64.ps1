# Build the Win64 JSBSim library the vendored UE plugin links against.
#
#     .\scripts\build_jsbsim_win64.ps1
#
# The repo vendors the plugin's source, headers, aircraft data and the FOUR
# local patches (VENDORED.json), but ships only the macOS library
# (Lib\Mac\libJSBSim.dylib). On Win64 the plugin's Build.cs links
# Source\ThirdParty\JSBSim\Lib\JSBSim.lib and stages JSBSim.dll from the same
# folder -- this script produces both, the vendor_ue_plugin.sh way: run
# UPSTREAM's own build (JSBSimForUnreal.sln, whose Release x64 output dir IS
# the plugin's Lib folder) inside a checkout of the exact version pinned in
# VENDORED.json, rather than reimplementing their build. Two JSBSim versions
# across the two hosts would make the physics-parity claim untestable by
# construction, so the commit is verified, not trusted.
#
# Needs: git, and Visual Studio 2022 with the MSVC C++ toolset
# ("Game development with C++" or "Desktop development with C++" workload).

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$Plugin = "ue\Plugins\JSBSimFlightDynamicsModel"
$Vendored = Get-Content "$Plugin\VENDORED.json" -Raw | ConvertFrom-Json
$Tag = $Vendored.tag
$Commit = $Vendored.commit
$Upstream = "https://github.com/JSBSim-Team/jsbsim.git"
$Work = Join-Path $env:TEMP "flightsim-vendor"
$Src = Join-Path $Work "jsbsim-$Tag"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required (winget install Git.Git)"
}
$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $VsWhere)) {
    throw "Visual Studio 2022 not found -- install it with the 'Game development with C++' workload"
}
$MsBuild = & $VsWhere -latest -products * `
    -requires Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -find MSBuild\**\Bin\MSBuild.exe 2>$null | Select-Object -First 1
if (-not $MsBuild) {
    throw "no MSBuild with the MSVC C++ toolset -- add the 'Game development with C++' workload in the VS installer"
}

if (-not (Test-Path (Join-Path $Src ".git"))) {
    Write-Host "==> fetching JSBSim $Tag (library sources and upstream build)"
    New-Item -ItemType Directory -Force -Path $Work | Out-Null
    git clone --depth 1 --branch $Tag $Upstream $Src
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
$Actual = git -C $Src rev-parse HEAD
if ($Actual -ne $Commit) {
    throw "checkout at $Actual but VENDORED.json pins $Commit -- refusing to build a different JSBSim than the headless core runs"
}

Write-Host "==> building JSBSimForUnreal.sln 1_Release x64 (upstream's own build; a few minutes)"
# Upstream names its solution configurations 1_Release / 2_Debug (the digit
# prefixes order them in the VS dropdown); "Release" is only the project-level
# name and msbuild rejects it at the solution level (measured: MSB4126).
& $MsBuild (Join-Path $Src "JSBSimForUnreal.sln") /m /p:Configuration=1_Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw "msbuild failed (exit $LASTEXITCODE)" }

# Release x64's OutDir is upstream's own plugin Lib folder; take the two
# files our vendored plugin's Build.cs actually uses. Headers, aircraft data
# and the local patches are already vendored here -- deliberately NOT copied.
$UpstreamLib = Join-Path $Src "UnrealEngine\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib"
$DestLib = "$Plugin\Source\ThirdParty\JSBSim\Lib"
foreach ($File in "JSBSim.lib", "JSBSim.dll") {
    $From = Join-Path $UpstreamLib $File
    if (-not (Test-Path $From)) { throw "$File not produced at $UpstreamLib" }
    Copy-Item $From (Join-Path $DestLib $File) -Force
}

Write-Host ""
Write-Host "built    JSBSim $Tag @ $($Commit.Substring(0,12)) for Win64"
foreach ($File in "JSBSim.lib", "JSBSim.dll") {
    $Path = Join-Path $DestLib $File
    $Hash = (Get-FileHash $Path -Algorithm SHA256).Hash.ToLower()
    Write-Host ("  {0,-12} sha256 {1}" -f $File, $Hash)
}
Write-Host ""
Write-Host "The library is built per machine and NOT committed (.gitignore);"
Write-Host "next: .\scripts\ue_preflight.ps1 then .\scripts\build_ue.ps1"
