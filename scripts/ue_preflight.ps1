# Check whether this Windows machine can build and run the Unreal host,
# and say exactly why not -- the ue_preflight.sh twin.
#
# Run from the repo root in PowerShell:  .\scripts\ue_preflight.ps1

# -FromLauncher: the launcher builds the materials after this step, so their
# absence on a fresh download is reported, not failed.
param([switch]$FromLauncher)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:status = 0

# Run a native command with its stderr discarded SAFELY. Under
# $ErrorActionPreference = "Stop", Windows PowerShell 5.1 turns a
# REDIRECTED stderr line into a terminating error -- so `... 2>$null`,
# which reads as "I do not care what it says on stderr", is in fact
# "die if it says anything at all". Both probes below are asked in the
# expectation that they may fail: a machine without the VS2022 v143
# toolset, and a .venv without jsbsim. Preflight exists to REPORT those,
# and each unguarded redirect turned its own Fail line into an
# unreachable branch. (setup.ps1 and deploy_windows.ps1 already carry
# this wrapper; report_run.ps1 carries its git twin.)
function Probe {
    param([string]$exe, [string[]]$probeArgs)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return & $exe @probeArgs 2>$null }
    catch { $global:LASTEXITCODE = 1; return $null }
    finally { $ErrorActionPreference = $old }
}

function Say($label, $msg)  { "  {0,-34} {1}" -f $label, $msg | Write-Host }
function Fail($label, $msg) { "  {0,-34} {1}" -f $label, $msg | Write-Host; $script:status = 1 }

Write-Host "Unreal host preflight (Windows)"
Write-Host ""

# -- engine ---------------------------------------------------------------
. (Join-Path $PSScriptRoot "ue_engine.ps1")
$engine = Resolve-PinnedEngine $repo
$pin = $engine.Pinned
$ueRoot = $engine.Root
if ($engine.Found) {
    Say "engine" "UE $($engine.Found) at $ueRoot"
    $mismatch = Test-EngineVersion $engine
    if ($mismatch) { Fail "engine" $mismatch }
} else {
    Fail "engine" "not found at $ueRoot (install UE $pin from the Epic Games Launcher, or set UE_ROOT)"
}
$editor = Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if (-not (Test-Path $editor)) {
    Fail "editor binary" "no UnrealEditor-Cmd.exe under $ueRoot"
}

# -- Visual Studio 2022 C++ toolchain ------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    # -products * : without it vswhere reports only Community/Professional/
    # Enterprise and says FAILED on a machine whose C++ workload lives in
    # Build Tools (the v143 probe below already passes it; this call did
    # not, and the Phase 1 report recorded the false alarm).
    $vs = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property catalog_productDisplayVersion | Select-Object -First 1
    if ($vs) {
        Say "visual studio (C++ tools)" "$vs"
        # The pinned UE is built against VS2022's v143 toolset, and so is the
        # JSBSim vendor build. A NEWER Visual Studio alone is not enough
        # -- measured on a machine with only VS2026 (v180): MSB8020.
        $v143 = Probe $vswhere @("-latest", "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.14.3x.17.14.x86.x64",
            "-property", "installationPath")
        if (-not $v143) {
            $v143 = Get-ChildItem "C:\Program Files*\Microsoft Visual Studio\2022" `
                -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if (-not $v143) {
            $v143 = Get-ChildItem "C:\Program Files*\Microsoft Visual Studio\*\*\VC\Tools\MSVC\14.4*" `
                -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        # The pinned engine lists VS2022 v143; whether it ALSO accepts a
        # newer toolset is not measured here.
        if ($v143) { Say "v143 toolset (UE $pin needs it)" "present" }
        else {
            Fail "v143 toolset (UE $pin needs it)" "MISSING -- a newer VS alone will not build UE $pin"
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
    # The vendor script records the engine it targeted; a VENDORED.json
    # without the key predates the pin and its three patched upstream bugs
    # (NEXT.md gotcha 32) were measured on an older engine. A note, not a Fail: the
    # native JSBSim library does not link the engine, the plugin sources
    # are compiled by UBT against whatever engine builds them.
    if ($vendored.ue_engine_target) {
        if ("$($vendored.ue_engine_target)" -eq $pin) {
            Say "jsbsim plugin engine target" "vendored for UE $($vendored.ue_engine_target)"
        } else {
            Say "jsbsim plugin engine target" ("vendored for UE $($vendored.ue_engine_target), project pins $pin " +
                "-- re-run scripts\vendor_ue_plugin.ps1 and re-check the patches (NEXT.md gotcha 32)")
        }
    } else {
        Say "jsbsim plugin engine target" ("not recorded (vendored before the engine target was written) " +
            "-- re-run scripts\vendor_ue_plugin.ps1 on UE $pin and re-check the patches (NEXT.md gotcha 32)")
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
        $core = Probe $py @("-c",
            "import jsbsim,re;print(re.search(r'commit ([0-9a-f]+)', jsbsim.FGJSBBase().get_version()).group(1))")
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
} elseif ($FromLauncher) {
    Say "material assets" "missing -- the launcher's materials step builds them next"
} else {
    Fail "material assets" "missing -- run the build-time step below"
    Write-Host ("        & '$editor' '" + (Join-Path $repo "ue\FlightSim.uproject") +
                "' -run=pythonscript -script='" +
                (Join-Path $repo "scripts\ue_create_materials.py") +
                "' -unattended -nopause -nosplash -stdout")
}
# Physical-sky materials (-sky=, a stated time of day): the moon, the star
# discs and the night-lights drape. Physical-sky renders refuse without
# the first two (a missing night-lights material only drops the lights,
# recorded), and legacy renders need none, so their absence is reported,
# not failed; the step above creates them (it skips existing assets).
$skyMaterials = @("M_Moon", "M_StarEmissive", "M_TerrainImageryNight") |
    Where-Object { -not (Test-Path (Join-Path $materials "$_.uasset")) }
if ($skyMaterials.Count -eq 0) {
    Say "physical-sky materials" "M_Moon + M_StarEmissive + M_TerrainImageryNight present"
} else {
    Say "physical-sky materials" ("missing " + ($skyMaterials -join ", ") +
        " -- stated-time renders need them; re-run the step above")
}

# -- toolchain manifest ---------------------------------------------------
# toolchain.json at the repo root pins every tool in ONE file (Phase 3 B2,
# decisions 13 and 15): the engine (version, patch, changelist), the C++
# toolchain per platform (msvc + windows_sdk here; xcode on the Mac), Cesium
# for Unreal, ffmpeg, the venv Python and JSBSim. Each installed tool is
# read and compared as a string; a difference is a refusal BY NAME
# (toolchain.<tool>_mismatch: found X, pinned Y), a tool that is not
# installed is "not found", and a null pin is UNRECORDED (that platform has
# not measured it yet; never compared). ffmpeg used to be a note here
# (a Say, never a Fail); decision 15 makes a missing or wrong ffmpeg a
# failure like every other pinned tool. Keys starting with "_" are comments.

# -> the parsed manifest; throws toolchain.pin_unreadable.
function Get-Toolchain($repo) {
    $manifest = Join-Path $repo "toolchain.json"
    if (-not (Test-Path $manifest)) {
        throw "toolchain.pin_unreadable: no manifest at $manifest"
    }
    try { $pins = Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "toolchain.pin_unreadable: $manifest is not valid JSON ($($_.Exception.Message))" }
    if ((-not $pins.engine) -or (-not $pins.engine.version)) {
        throw "toolchain.pin_unreadable: $manifest has no engine.version"
    }
    return $pins
}

# The one directory name under $parent that equals $pinned, else the highest
# one (so the mismatch names what IS installed), else $null.
function Select-VersionDir($parent, $pinned) {
    $dirs = Get-ChildItem $parent -Directory -ErrorAction SilentlyContinue
    if (-not $dirs) { return $null }
    $exact = $dirs | Where-Object { $_.Name -eq "$pinned" } | Select-Object -First 1
    if ($exact) { return $exact.Name }
    $sorted = $dirs | Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } }
    return ($sorted | Select-Object -Last 1).Name
}

# -> ordered map tool -> the installed version string, or $null when the
# tool is not installed. The engine string carries its changelist so the
# pin's changelist is compared too: "M.m.p (CL n)".
function Get-InstalledTools($repo, $ueRoot, $pins) {
    $found = [ordered]@{}

    $buildVersion = Join-Path $ueRoot "Engine\Build\Build.version"
    $found.engine = $null
    if (Test-Path $buildVersion) {
        $v = Get-Content $buildVersion -Raw | ConvertFrom-Json
        $found.engine = "$($v.MajorVersion).$($v.MinorVersion).$($v.PatchVersion) (CL $($v.Changelist))"
    }

    $found.msvc = $null
    $vswhereExe = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhereExe) {
        $vsPath = Probe $vswhereExe @("-latest", "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath") | Select-Object -First 1
        if ($vsPath) {
            $found.msvc = Select-VersionDir (Join-Path $vsPath "VC\Tools\MSVC") $pins.windows.msvc
        }
    }

    $found.windows_sdk = Select-VersionDir `
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\Include") $pins.windows.windows_sdk

    $found.cesium_for_unreal = $null
    $uplugin = Get-ChildItem (Join-Path $ueRoot "Engine\Plugins\Marketplace") `
        -Recurse -Depth 1 -Filter "CesiumForUnreal.uplugin" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($uplugin) {
        $descriptor = Get-Content $uplugin.FullName -Raw | ConvertFrom-Json
        if ($descriptor.VersionName) { $found.cesium_for_unreal = "$($descriptor.VersionName)" }
    }

    $found.ffmpeg = $null
    $ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpegCmd) {
        $banner = Probe $ffmpegCmd.Source @("-version") | Select-Object -First 1
        if ("$banner" -match "version (\d+\.\d+(\.\d+)?)") { $found.ffmpeg = $Matches[1] }
    }

    $found.python = $null
    $found.jsbsim = $null
    $venvPy = Join-Path $repo ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        # Capture Probe's output whole and read $LASTEXITCODE RIGHT AFTER the
        # call, then take the first line. Piping a native command straight
        # into `Select-Object -First 1` stops its pipeline early in Windows
        # PowerShell 5.1 and leaves $LASTEXITCODE at -1, so a correctly
        # printed version was thrown away (B2 packet 1: jsbsim 1.2.4
        # installed, preflight said "not found"). Probe's catch still sets
        # $LASTEXITCODE = 1 when the interpreter cannot start at all.
        $pyBanner = @(Probe $venvPy @("--version"))
        $pyExit = $LASTEXITCODE
        $pyLine = "$($pyBanner | Select-Object -First 1)"
        if ($pyExit -eq 0 -and $pyLine -match "(\d+\.\d+\.\d+)") { $found.python = $Matches[1] }
        $jsb = @(Probe $venvPy @("-c", "import importlib.metadata as m;print(m.version('jsbsim'))"))
        $jsbExit = $LASTEXITCODE
        $jsbLine = "$($jsb | Select-Object -First 1)".Trim()
        if ($jsbExit -eq 0 -and $jsbLine) { $found.jsbsim = $jsbLine }
    }
    return $found
}

# One line per tool: "OK <tool> <version>" through Say, a mismatch or a
# missing tool through Fail (exit non-zero), a null pin as UNRECORDED.
function Test-ToolVersion($tool, $found, $pinned) {
    if ($null -eq $pinned) { Say "toolchain $tool" "UNRECORDED $tool"; return }
    if (-not $found) {
        Fail "toolchain $tool" "toolchain.${tool}_mismatch: not found, pinned $pinned"
        return
    }
    if ("$found" -ne "$pinned") {
        Fail "toolchain $tool" "toolchain.${tool}_mismatch: found $found, pinned $pinned"
        return
    }
    Say "toolchain $tool" "OK $tool $found"
}

$pins = $null
try { $pins = Get-Toolchain $repo }
catch { Fail "toolchain manifest" $_.Exception.Message }
if ($pins) {
    $installed = Get-InstalledTools $repo $ueRoot $pins
    $enginePin = "$($pins.engine.version).$($pins.engine.patch)"
    if ($pins.engine.changelist) { $enginePin = "$enginePin (CL $($pins.engine.changelist))" }
    Test-ToolVersion "engine" $installed.engine $enginePin
    $platformPins = $pins.windows
    if ($platformPins) {
        foreach ($entry in $platformPins.PSObject.Properties) {
            if ($entry.Name.StartsWith("_")) { continue }
            Test-ToolVersion $entry.Name $installed[$entry.Name] $entry.Value
        }
    } else {
        Fail "toolchain manifest" "toolchain.pin_unreadable: no 'windows' block in toolchain.json"
    }
    foreach ($entry in $pins.PSObject.Properties) {
        if ($entry.Name.StartsWith("_")) { continue }
        if ($entry.Name -in @("engine", "windows", "mac")) { continue }
        Test-ToolVersion $entry.Name $installed[$entry.Name] $entry.Value
    }
}

Write-Host ""
if ($script:status -eq 0) {
    Write-Host "Preflight OK -- the Unreal host can run here."
    Write-Host "Validate the render output on THIS machine with:"
    Write-Host "  .\.venv\Scripts\python.exe experiments\gate6_visual.py"
} else {
    Write-Host "Preflight FAILED -- see above."
}
exit $script:status
