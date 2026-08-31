# Check whether this Windows machine can build and run the Unreal host, and
# say exactly why not. The ue_preflight.sh twin -- same checks, Windows
# toolchain: Visual Studio 2022 with the C++ game/desktop workload instead of
# Xcode, and the vendored JSBSim library is JSBSim.lib + JSBSim.dll built
# locally by scripts\build_jsbsim_win64.ps1 (the repo ships only the Mac
# dylib; see docs\WINDOWS.md).
#
# Run from the repo root:  .\scripts\ue_preflight.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$STATUS = 0
function Say([string]$What, [string]$Detail) {
    Write-Host ("  {0,-34} {1}" -f $What, $Detail)
}
function Fail([string]$What, [string]$Detail) {
    Write-Host ("  {0,-34} {1}" -f $What, $Detail)
    $script:STATUS = 1
}

Write-Host "Unreal host preflight (Windows)"
Write-Host ""

# -- engine -----------------------------------------------------------------
# Same resolution order as core/util/platform.py: UNREAL_EDITOR_EXE ->
# UE_ROOT -> the launcher's default install root.
$UERoot = $null
if ($env:UNREAL_EDITOR_EXE -and (Test-Path $env:UNREAL_EDITOR_EXE)) {
    # ...\Engine\Binaries\Win64\UnrealEditor-Cmd.exe -> engine root
    $UERoot = (Get-Item $env:UNREAL_EDITOR_EXE).Directory.Parent.Parent.Parent.FullName
} elseif ($env:UE_ROOT -and (Test-Path $env:UE_ROOT)) {
    $UERoot = $env:UE_ROOT
} elseif (Test-Path "C:\Program Files\Epic Games\UE_5.5") {
    $UERoot = "C:\Program Files\Epic Games\UE_5.5"
}

if ($UERoot) {
    $VersionFile = Join-Path $UERoot "Engine\Build\Build.version"
    $Version = "unknown"
    if (Test-Path $VersionFile) {
        $v = Get-Content $VersionFile -Raw | ConvertFrom-Json
        $Version = "$($v.MajorVersion).$($v.MinorVersion).$($v.PatchVersion)"
    }
    Say "engine" "UE $Version at $UERoot"
    $EditorCmd = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
    if (Test-Path $EditorCmd) {
        Say "editor commandlet binary" "UnrealEditor-Cmd.exe present"
    } else {
        Fail "editor commandlet binary" "missing at $EditorCmd"
    }
} else {
    Fail "engine" "not found (set UNREAL_EDITOR_EXE or UE_ROOT, or install UE 5.5 at the default location)"
}

# -- the vendored plugin ----------------------------------------------------
$Plugin = "ue\Plugins\JSBSimFlightDynamicsModel"
if (Test-Path "$Plugin\VENDORED.json") {
    $Vendored = Get-Content "$Plugin\VENDORED.json" -Raw | ConvertFrom-Json
    # The plugin's Build.cs on Win64 links Source\ThirdParty\JSBSim\Lib\
    # JSBSim.lib and stages JSBSim.dll from the same folder (note: directly
    # in Lib\, not Lib\Win64\ -- upstream's own convention).
    $Lib = "$Plugin\Source\ThirdParty\JSBSim\Lib\JSBSim.lib"
    $Dll = "$Plugin\Source\ThirdParty\JSBSim\Lib\JSBSim.dll"
    if ((Test-Path $Lib) -and (Test-Path $Dll)) {
        Say "jsbsim win64 library" "JSBSim.lib + JSBSim.dll present ($($Vendored.tag))"
    } else {
        Fail "jsbsim win64 library" "missing -- run scripts\build_jsbsim_win64.ps1 (the repo ships only the Mac dylib)"
    }
    if ($Vendored.aircraft_staged -gt 0) {
        Say "jsbsim runtime data" "$($Vendored.aircraft_staged) aircraft staged in Resources\JSBSim"
    } else {
        Fail "jsbsim runtime data" "Resources\JSBSim is empty -- the host would have no aircraft to load"
    }
    # Both hosts must run the same JSBSim, or the parity claim is untestable.
    $Core = $null
    if (Test-Path ".venv\Scripts\python.exe") {
        $Core = & .venv\Scripts\python.exe -c "import jsbsim,re;print(re.search(r'commit ([0-9a-f]+)', jsbsim.FGJSBBase().get_version()).group(1))" 2>$null
    }
    if ($Core -eq $Vendored.commit) {
        Say "jsbsim parity" "both hosts at $($Core.Substring(0,12))"
    } elseif ($Core) {
        Fail "jsbsim parity" "headless $($Core.Substring(0,12)) != plugin $($Vendored.commit.Substring(0,12))"
    } else {
        Fail "jsbsim parity" "headless jsbsim not importable (run scripts\setup.ps1 first)"
    }
} else {
    Fail "jsbsim plugin" "not vendored"
}

# -- the bridge -------------------------------------------------------------
$BridgeSources = (Get-ChildItem "ue\Plugins\FlightSimBridge\Source" -Recurse -Filter "*.cpp" -ErrorAction SilentlyContinue).Count
if ($BridgeSources -gt 0) {
    Say "flightsim bridge" "$BridgeSources translation units"
} else {
    Fail "flightsim bridge" "no sources"
}

# -- the toolchain ----------------------------------------------------------
# UE 5.5 builds with Visual Studio 2022 + the MSVC C++ toolset and a Windows
# SDK -- the "Game development with C++" (or "Desktop development with C++")
# workload carries both. vswhere is installed with every VS 2022.
$VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$Vs = $null
if (Test-Path $VsWhere) {
    $Vs = & $VsWhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath 2>$null | Select-Object -First 1
}
if ($Vs) {
    $VsVersion = & $VsWhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property catalog_productDisplayVersion 2>$null | Select-Object -First 1
    Say "visual studio (build toolchain)" "VS $VsVersion at $Vs"
} else {
    Fail "visual studio (build toolchain)" "no VS 2022 with the MSVC C++ toolset -- install the 'Game development with C++' workload"
}

# -- did it actually build? -------------------------------------------------
$BridgeDll = "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (Test-Path $BridgeDll) {
    Say "bridge binary" "built"
} else {
    Fail "bridge binary" "not built yet -- run scripts\build_ue.ps1"
}

Write-Host ""
if ($STATUS -eq 0) {
    Write-Host "Preflight OK -- the Unreal host can be built and run."
} else {
    Write-Host "Preflight FAILED -- see above and docs\WINDOWS.md."
}
exit $STATUS
