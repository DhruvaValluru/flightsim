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

Write-Host ""
Write-Host "== 1/3 download + convert aircraft models =="
foreach ($Name in $Aircraft) {
    $Config = "assets\aircraft_config\$Name.json"
    $Manifest = "assets\generated\$Name\mesh_manifest.json"
    if (-not (Test-Path $Config)) { Write-Host "  $Name : no $Config, skipped"; continue }
    if (Test-Path $Manifest) { Write-Host "  $Name : already converted"; continue }
    Write-Host "  $Name : downloading + converting (a few minutes)..."
    & $Python assets_pipeline\convert.py $Config
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Manifest)) {
        Write-Host "  $Name : CONVERT FAILED (exit $LASTEXITCODE)"
        $Failed += "convert $Name"
    }
}

Write-Host ""
Write-Host "== 2/3 import into the Unreal project =="
Write-Host "  creating materials..."
& $Editor $Project -run=pythonscript -script="$PWD\scripts\ue_create_materials.py" `
    -unattended -nopause -nosplash -stdout | Select-String -Pattern "error|Error|created|Material" | Select-Object -First 10
if ($LASTEXITCODE -ne 0) { $Failed += "ue_create_materials (exit $LASTEXITCODE)" }
foreach ($Name in $Aircraft) {
    $Manifest = Join-Path (Get-Location) "assets\generated\$Name\mesh_manifest.json"
    if (-not (Test-Path $Manifest)) { Write-Host "  $Name : no manifest, skipped"; continue }
    Write-Host "  $Name : importing meshes..."
    & $Editor $Project -run=pythonscript -script="$PWD\scripts\ue_import_aircraft.py $Manifest" `
        -unattended -nopause -nosplash -stdout | Select-String -Pattern "error|Error|FAIL|imported|bounds" | Select-Object -First 15
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  $Name : IMPORT FAILED (exit $LASTEXITCODE)"
        $Failed += "import $Name"
    }
}

Write-Host ""
Write-Host "== 3/3 bake real terrain (Copernicus GLO-30 download, a few minutes each) =="
foreach ($Key in $Terrains) {
    if (Test-Path "runs\terrain\$Key.r16") { Write-Host "  $Key : already baked"; continue }
    Write-Host "  $Key : fetching + baking..."
    & $Python -c "from pathlib import Path; from core.terrain.glo30 import LOCATIONS, bake; bake(LOCATIONS['$Key'], Path('data/glo30'), Path('runs/terrain'))"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  $Key : BAKE FAILED (exit $LASTEXITCODE)"
        $Failed += "bake $Key"
    }
}

Write-Host ""
if ($Failed.Count -eq 0) {
    Write-Host "Visual setup complete. Meshes on disk:"
    Get-ChildItem "assets\generated\*\mesh_manifest.json" -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "  $($_.Directory.Name)" }
    Write-Host "Terrains baked:"
    Get-ChildItem "runs\terrain\*.r16" -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "  $($_.BaseName)" }
    Write-Host ""
    Write-Host "Start the webapp and prompt e.g.: fly the 747 over yosemite at 250 kt"
} else {
    Write-Host "FAILED steps: $($Failed -join ', ')"
    Write-Host "Re-run this script after fixing; finished steps are skipped."
    exit 1
}
