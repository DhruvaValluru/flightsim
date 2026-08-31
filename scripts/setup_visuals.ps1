# One command from placeholder boxes to real aircraft over real terrain.
#
#     .\scripts\setup_visuals.ps1
#
# Runs the three per-machine visual setup steps the repo cannot ship
# (licensed 3-D models and satellite terrain are downloaded and built per
# machine, never committed):
#
#   1. download + convert the licensed aircraft models (assets_pipeline)
#   2. import them into the Unreal project (materials + meshes, via the
#      editor's python commandlet)
#   3. bake real Copernicus GLO-30 terrain for the curated scenes
#
# Idempotent: finished steps are detected and skipped, so re-running after
# a failure continues where it stopped. The webapp/editor must NOT be
# running (step 2 needs the editor to itself).

param(
    # Aircraft to set up (must have a config in assets\aircraft_config).
    [string[]]$Aircraft = @("B747", "c172p"),
    # Terrains to bake (keys of core.terrain.glo30.LOCATIONS).
    [string[]]$Terrains = @("yosemite", "flint_hills", "matterhorn")
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "no .venv -- run scripts\setup.ps1 first" }

# Same resolution order as core/util/platform.py.
if ($env:UNREAL_EDITOR_EXE -and (Test-Path $env:UNREAL_EDITOR_EXE)) {
    $Editor = $env:UNREAL_EDITOR_EXE
} else {
    $UERoot = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.5" }
    $Editor = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
}
if (-not (Test-Path $Editor)) { throw "no editor at $Editor (set UNREAL_EDITOR_EXE or UE_ROOT)" }
if (-not (Test-Path "ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll")) {
    throw "the bridge is not built -- run scripts\build_ue.ps1 first"
}

# Step 2 needs the editor to itself; a running webapp render would collide.
$Probe = tasklist /FI "IMAGENAME eq UnrealEditor*" 2>$null
if ($Probe -match "UnrealEditor") {
    throw "an Unreal editor process is running -- stop the webapp (Ctrl+C) and wait for any render to finish, then re-run this"
}

$Project = Join-Path (Get-Location) "ue\FlightSim.uproject"
$Failed = @()

New-Item -ItemType Directory -Force -Path "runs" | Out-Null

Write-Host ""
Write-Host "== 1/4 download + convert aircraft models =="
foreach ($Name in $Aircraft) {
    $Config = "assets\aircraft_config\$Name.json"
    $Manifest = "assets\generated\$Name\mesh_manifest.json"
    if (-not (Test-Path $Config)) { Write-Host "  $Name : no $Config, skipped"; continue }
    if (Test-Path $Manifest) { Write-Host "  $Name : already converted"; continue }

    # convert.py does NOT fetch: it expects the licensed model repo already
    # checked out at the config's pinned commit (the Mac had these clones
    # from long ago). Clone-or-update here, license-file presence as the
    # done-marker -- the same file convert.py refuses without.
    $Cfg = Get-Content $Config -Raw | ConvertFrom-Json
    $Src = Join-Path "assets" ($Cfg.source_dir -replace '^\.\./', '')
    $LicensePath = Join-Path $Src $Cfg.license.file
    if (-not (Test-Path $LicensePath)) {
        Write-Host "  $Name : fetching model source ($($Cfg.license.repo) @ $($Cfg.license.commit.Substring(0,10)))..."
        if (-not (Test-Path (Join-Path $Src ".git"))) {
            git clone --filter=blob:none $Cfg.license.repo $Src
            if ($LASTEXITCODE -ne 0) { git clone $Cfg.license.repo $Src }
        }
        git -C $Src checkout --quiet $Cfg.license.commit
        if ($LASTEXITCODE -ne 0) {
            git -C $Src fetch origin
            git -C $Src checkout --quiet $Cfg.license.commit
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $LicensePath)) {
            Write-Host "  $Name : SOURCE FETCH FAILED"
            $Failed += "fetch $Name"
            continue
        }
    }

    Write-Host "  $Name : converting..."
    & $Python assets_pipeline\convert.py $Config
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Manifest)) {
        Write-Host "  $Name : CONVERT FAILED (exit $LASTEXITCODE)"
        $Failed += "convert $Name"
    }
}

Write-Host ""
Write-Host "== 2/4 import into the Unreal project =="
Write-Host "  creating materials (full log: runs\setup_visuals_materials.log)..."
# ABSOLUTE paths with FORWARD slashes -- both measured failures rule out
# the alternatives: a backslashed absolute path loses its \u sequence in
# the command-line handoff ('scripts\ue_import_aircraft.py' arrived as
# 'scripts_import_aircraft.py'), and a relative path resolves against the
# editor's own Binaries\Win64 directory, not the CWD.
$Root = (Get-Location).Path -replace '\\', '/'
& $Editor $Project -run=pythonscript -script="$Root/scripts/ue_create_materials.py" `
    -unattended -nopause -nosplash -stdout *> "runs\setup_visuals_materials.log"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ue_create_materials exited $LASTEXITCODE; log tail:"
    Get-Content "runs\setup_visuals_materials.log" -Tail 20 | ForEach-Object { Write-Host "    $_" }
    $Failed += "ue_create_materials (exit $LASTEXITCODE)"
}
foreach ($Name in $Aircraft) {
    $Manifest = "assets/generated/$Name/mesh_manifest.json"
    if (-not (Test-Path $Manifest)) { Write-Host "  $Name : no manifest, skipped"; continue }
    $ImportLog = "runs\setup_visuals_import_$Name.log"
    Write-Host "  $Name : importing meshes (full log: $ImportLog)..."
    & $Editor $Project -run=pythonscript -script="$Root/scripts/ue_import_aircraft.py $Root/$Manifest" `
        -unattended -nopause -nosplash -stdout *> $ImportLog
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  $Name : IMPORT FAILED (exit $LASTEXITCODE); log tail:"
        Get-Content $ImportLog -Tail 20 | ForEach-Object { Write-Host "    $_" }
        $Failed += "import $Name"
    }
}

Write-Host ""
Write-Host "== 3/4 bake real terrain (Copernicus GLO-30 download, a few minutes each) =="
foreach ($Key in $Terrains) {
    if (Test-Path "runs\terrain\$Key.r16") { Write-Host "  $Key : already baked"; continue }
    Write-Host "  $Key : fetching + baking..."
    & $Python -c "from pathlib import Path; from core.terrain.glo30 import LOCATIONS, bake; bake(LOCATIONS['$Key'], Path('data/glo30'), Path('runs/terrain'))"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  $Key : BAKE FAILED (exit $LASTEXITCODE)"
        $Failed += "bake $Key"
    }
}

# The elevation raster alone renders with the fallback height-coloured
# material (the flat-shaded pastel look); the REALISTIC look is Sentinel-2
# cloudless satellite imagery draped over the bake -- the render picks up
# <key>_imagery.json automatically once it exists (webapp/runs.py
# pick_scene). drape() verifies the texture against its source and refuses
# to write an unverified one.
Write-Host ""
Write-Host "== 4/4 drape satellite imagery over the bakes (Sentinel-2 download, a few minutes each) =="
foreach ($Key in $Terrains) {
    if (-not (Test-Path "runs\terrain\$Key.r16")) { Write-Host "  $Key : not baked, skipped"; continue }
    if (Test-Path "runs\terrain\$Key`_imagery.json") { Write-Host "  $Key : imagery already draped"; continue }
    Write-Host "  $Key : fetching + draping satellite imagery..."
    & $Python -c "from pathlib import Path; from core.terrain.glo30 import LOCATIONS; from core.terrain.imagery import drape; drape(LOCATIONS['$Key'], Path('runs/terrain/$Key'), Path('data/imagery'), Path('runs/terrain'))"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  $Key : IMAGERY FAILED (exit $LASTEXITCODE)"
        $Failed += "imagery $Key"
    }
}

Write-Host ""
if ($Failed.Count -eq 0) {
    Write-Host "Visual setup complete. Meshes on disk:"
    Get-ChildItem "assets\generated\*\mesh_manifest.json" -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "  $($_.Directory.Name)" }
    Write-Host "Terrains baked (i = satellite imagery draped):"
    Get-ChildItem "runs\terrain\*.r16" -ErrorAction SilentlyContinue | ForEach-Object {
        $Mark = if (Test-Path "runs\terrain\$($_.BaseName)_imagery.json") { " (i)" } else { "" }
        Write-Host "  $($_.BaseName)$Mark"
    }
    Write-Host ""
    Write-Host "Start the webapp and prompt e.g.: fly the 747 over yosemite at 250 kt"
} else {
    Write-Host "FAILED steps: $($Failed -join ', ')"
    Write-Host "Re-run this script after fixing; finished steps are skipped."
    exit 1
}
