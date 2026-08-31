# Rendering on Windows

The headless half (prompt → spec → validation → physics → telemetry → web
app) runs on Windows with nothing but `.\scripts\setup.ps1`. This page is
the extra path to **rendered video clips**: the same Unreal host the Mac
runs, gated on capability ("is an editor actually here", found by
`core/util/platform.py`), not on the OS name.

One honesty note up front: every render calibration (exposure, fog
density, camera framing) was measured on Metal/macOS first. The flags all
work identically on D3D12, but expect the first clips to read slightly
differently -- that is tuning, not breakage.

## What you need installed

1. **Unreal Engine 5.5** (5.5.4 from the Epic Games Launcher is 5.5).
   The default install location, `C:\Program Files\Epic Games\UE_5.5`, is
   found automatically. Anywhere else: set `UE_ROOT` to the install root,
   or `UNREAL_EDITOR_EXE` to
   `...\Engine\Binaries\Win64\UnrealEditor-Cmd.exe` (the `-Cmd` binary --
   it is the one that runs commandlets; plain `UnrealEditor.exe` is the
   GUI).
2. **Visual Studio 2022** with the **"Game development with C++"**
   workload (installs the MSVC C++ toolset and a Windows SDK). If VS is
   already installed without it, add the workload in the Visual Studio
   Installer.
3. **git** and **ffmpeg** (`winget install Git.Git`,
   `winget install ffmpeg`).
4. Python deps: `.\scripts\setup.ps1` from the repo root, if not done
   already.

## Step 1 -- build the Win64 JSBSim library (the one extra Windows step)

The vendored UE plugin links a prebuilt JSBSim; the repo ships only the
Mac `libJSBSim.dylib`. On Win64 the plugin's `Build.cs` expects
`JSBSim.lib` + `JSBSim.dll` directly in
`ue\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib\`.
Build them with:

```powershell
.\scripts\build_jsbsim_win64.ps1
```

It clones JSBSim at the exact tag pinned in the plugin's `VENDORED.json`
(refusing any other commit -- both hosts must run the same JSBSim or the
physics-parity claim is untestable), runs upstream's own
`JSBSimForUnreal.sln` Release x64 build, and copies the two files into
place. They are per-machine artifacts and gitignored, never committed.

## Step 2 -- preflight and build the Unreal host

```powershell
.\scripts\ue_preflight.ps1     # says exactly what is missing, if anything
.\scripts\build_ue.ps1         # first build takes a long while (possibly an hour)
```

## Step 3 -- materials and aircraft meshes (for real aircraft visuals)

Same build-time steps as the Mac, with the Windows editor binary. First
convert the licensed models (downloads + converts, writes
`assets\generated\<name>\mesh_manifest.json`):

```powershell
.\.venv\Scripts\python.exe assets_pipeline\convert.py
```

Then, with `$Editor = "C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"`
(or your `UNREAL_EDITOR_EXE`) and from the repo root:

```powershell
& $Editor "$PWD\ue\FlightSim.uproject" -run=pythonscript -script="$PWD\scripts\ue_create_materials.py" -unattended -nopause -nosplash -stdout
& $Editor "$PWD\ue\FlightSim.uproject" -run=pythonscript -script="$PWD\scripts\ue_import_aircraft.py $PWD\assets\generated\B747\mesh_manifest.json" -unattended -nopause -nosplash -stdout
```

(repeat the import for each aircraft under `assets\generated\`). Without
imported meshes the pipeline still runs but refuses to render aircraft
that would show placeholder boxes -- by name, as everywhere.

## Step 4 -- prove the render from the terminal before the web app

This ordering separates "the UE project doesn't build/render on Win64"
from "the webapp wiring is wrong":

```powershell
.\scripts\render_ue_scenario.ps1 <run-card.json> <frames-out-dir>
```

Any existing run card works (`runs\webapp\<run_id>\card.json` from a
previous attempt, or one written by the gates). Success prints the frame
count and writes `render.json` in the frames dir.

## Step 5 -- the web app

```powershell
.\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008
```

Open http://127.0.0.1:8008, type a prompt, Interpret, Run. The status
line's `render_available` now answers the same capability check the
scripts use. If you set `UNREAL_EDITOR_EXE`/`UE_ROOT`, set them in the
same PowerShell session that starts uvicorn (the editor path is resolved
at server start).

## Named refusals you might meet, and their fixes

| refusal / failure | fix |
|---|---|
| `ue.platform` (no Unreal editor found) | install UE 5.5 at the default path, or set `UNREAL_EDITOR_EXE` / `UE_ROOT` for the uvicorn session |
| `JSBSim.lib not found` at build time | step 1 (`build_jsbsim_win64.ps1`) |
| `the bridge is not built` | step 2 (`build_ue.ps1`) |
| `aircraft.mesh` (placeholder never renders) | step 3 for that aircraft |
| `ffmpeg.missing` | `winget install ffmpeg` (new terminal afterwards) |
