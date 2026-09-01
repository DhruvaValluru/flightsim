# Check whether this Windows machine can build and run the Unreal host,
# and say exactly why not -- the ue_preflight.sh twin.
#
# Run from the repo root in PowerShell:  .\scripts\ue_preflight.ps1

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:status = 0

function Say($label, $msg)  { "  {0,-34} {1}" -f $label, $msg | Write-Host }
function Fail($label, $msg) { "  {0,-34} {1}" -f $label, $msg | Write-Host; $script:status = 1 }

Write-Host "Unreal host preflight (Windows)"
Write-Host ""

# -- engine ---------------------------------------------------------------
$ueRoot = $env:UE_ROOT
if (-not $ueRoot) {
    $ueRoot = "C:\Program Files\Epic Games\UE_5.5"
    if (-not (Test-Path $ueRoot)) {
        $found = Get-ChildItem "C:\Program Files\Epic Games" -Directory `
            -Filter "UE_5.*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($found) { $ueRoot = $found.FullName }
    }
}
$versionFile = Join-Path $ueRoot "Engine\Build\Build.version"
if (Test-Path $versionFile) {
    $v = Get-Content $versionFile -Raw | ConvertFrom-Json
    $engine = "$($v.MajorVersion).$($v.MinorVersion).$($v.PatchVersion)"
    Say "engine" "UE $engine at $ueRoot"
    if ("$($v.MajorVersion).$($v.MinorVersion)" -ne "5.5") {
        Say "" ("note: the project pins EngineAssociation 5.5; the plugin " +
                "states UE5.0-5.6 compatibility, so $engine may work but " +
                "5.5 is what was measured")
    }
} else {
    Fail "engine" "not found at $ueRoot (install UE 5.5 from the Epic Games Launcher, or set UE_ROOT)"
}
$editor = Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if (-not (Test-Path $editor)) {
    Fail "editor binary" "no UnrealEditor-Cmd.exe under $ueRoot"
}

# -- Visual Studio 2022 C++ toolchain ------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vs = & $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property catalog_productDisplayVersion | Select-Object -First 1
    if ($vs) {
        Say "visual studio (C++ tools)" "$vs"
        # UE 5.5 is built against VS2022's v143 toolset, and so is the
        # JSBSim vendor build. A NEWER Visual Studio alone is not enough
        # -- measured on a machine with only VS2026 (v180): MSB8020.
        $v143 = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.14.3x.17.14.x86.x64 `
            -property installationPath 2>$null
        if (-not $v143) {
            $v143 = Get-ChildItem "C:\Program Files*\Microsoft Visual Studio\2022" `
                -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if (-not $v143) {
            $v143 = Get-ChildItem "C:\Program Files*\Microsoft Visual Studio\*\*\VC\Tools\MSVC\14.4*" `
                -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if ($v143) { Say "v143 toolset (UE 5.5 needs it)" "present" }
        else {
            Fail "v143 toolset (UE 5.5 needs it)" "MISSING -- a newer VS alone will not build UE 5.5"
            Write-Host "        winget install --id Microsoft.VisualStudio.2022.BuildTools ``"
            Write-Host "          --override `"--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools ``"
            Write-Host "          --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --includeRecommended`""
        }
    }
    else { Fail "visual studio (C++ tools)" "VS found but the 'Desktop development with C++' workload is missing" }
} else {
    Fail "visual studio (C++ tools)" "vswhere.exe not found -- install Visual Studio 2022 with the C++ workload"
}

# -- the vendored plugin --------------------------------------------------
$plugin = Join-Path $repo "ue\Plugins\JSBSimFlightDynamicsModel"
$vendoredJson = Join-Path $plugin "VENDORED.json"
if (Test-Path $vendoredJson) {
    $vendored = Get-Content $vendoredJson -Raw | ConvertFrom-Json
    Say "jsbsim plugin" "vendored $($vendored.tag) (patched sources committed)"
    $dll = Join-Path $plugin "Source\ThirdParty\JSBSim\Lib\JSBSim.dll"
    $lib = Join-Path $plugin "Source\ThirdParty\JSBSim\Lib\JSBSim.lib"
    if ((Test-Path $dll) -and (Test-Path $lib)) {
        Say "jsbsim Win64 library" "JSBSim.dll + JSBSim.lib present"
    } else {
        Fail "jsbsim Win64 library" "missing -- run scripts\vendor_ue_plugin.ps1"
    }
    $aircraft = Get-ChildItem (Join-Path $plugin "Resources\JSBSim\aircraft") `
        -Directory -ErrorAction SilentlyContinue
    if ($aircraft.Count -gt 0) {
        Say "jsbsim runtime data" "$($aircraft.Count) aircraft staged in Resources/JSBSim"
    } else {
        Fail "jsbsim runtime data" "Resources/JSBSim is empty"
    }
    # Both hosts must run the same JSBSim, or the parity claim is untestable.
    $py = Join-Path $repo ".venv\Scripts\python.exe"
    if (Test-Path $py) {
        $core = & $py -c "import jsbsim,re;print(re.search(r'commit ([0-9a-f]+)', jsbsim.FGJSBBase().get_version()).group(1))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $core -eq $vendored.commit) {
            Say "jsbsim parity" "both hosts at $($core.Substring(0,12))"
        } elseif ($LASTEXITCODE -eq 0) {
            Fail "jsbsim parity" "headless $($core.Substring(0,12)) != plugin $($vendored.commit.Substring(0,12))"
        } else {
            Fail "jsbsim parity" "could not read the headless jsbsim version (run scripts\setup.ps1?)"
        }
    } else {
        Fail "jsbsim parity" "no .venv -- run scripts\setup.ps1 first"
    }
} else {
    Fail "jsbsim plugin" "not vendored at $plugin"
}

# -- the bridge -----------------------------------------------------------
$bridgeSources = Get-ChildItem (Join-Path $repo "ue\Plugins\FlightSimBridge\Source") `
    -Recurse -Filter "*.cpp" -ErrorAction SilentlyContinue
if ($bridgeSources.Count -gt 0) {
    Say "flightsim bridge" "$($bridgeSources.Count) translation units"
} else {
    Fail "flightsim bridge" "no sources"
}

# -- did it actually build? ----------------------------------------------
$bridgeDll = Join-Path $repo "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll"
if (Test-Path $bridgeDll) {
    Say "bridge binary" "built"
} else {
    Fail "bridge binary" "not built yet -- run scripts\build_ue.ps1"
}

# -- build-time material assets ------------------------------------------
# The render commandlet REFUSES without these rather than falling back to
# the default material (which would render the terrain classification
# invisibly wrong). Measured: the first Windows render failed here only
# AFTER 10 minutes of first-run shader compilation, so name it up front.
$materials = Join-Path $repo "ue\Content\FlightSim"
$haveMaterials = @("M_VertexColor", "M_TerrainImagery") |
    Where-Object { Test-Path (Join-Path $materials "$_.uasset") }
if ($haveMaterials.Count -eq 2) {
    Say "material assets" "M_VertexColor + M_TerrainImagery present"
} else {
    Fail "material assets" "missing -- run the build-time step below"
    Write-Host ("        & '$editor' '" + (Join-Path $repo "ue\FlightSim.uproject") +
                "' -run=pythonscript -script='" +
                (Join-Path $repo "scripts\ue_create_materials.py") +
                "' -unattended -nopause -nosplash -stdout")
}

# -- ffmpeg (clips only; a named refusal elsewhere, stated here early) ----
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) { Say "ffmpeg (clip encoding)" $ffmpeg.Source }
else { Say "ffmpeg (clip encoding)" "not found -- winget install ffmpeg (renders still run; only encoding needs it)" }

Write-Host ""
if ($script:status -eq 0) {
    Write-Host "Preflight OK -- the Unreal host can run here."
    Write-Host "Validate the render output on THIS machine with:"
    Write-Host "  .\.venv\Scripts\python.exe experiments\gate6_visual.py"
} else {
    Write-Host "Preflight FAILED -- see above."
}
exit $script:status
