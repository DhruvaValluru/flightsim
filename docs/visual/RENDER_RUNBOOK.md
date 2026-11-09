# Visual overhaul: the render-machine runbook (Windows)

The visual overhaul was written on 2026-11-09 on a Mac that cannot compile
or render UE 5.7.4: Xcode 27.2 is above the engine's maximum of 26.9, and
Cesium for Unreal is not installed. **None of it has been built or
rendered.** This file is the exact Windows sequence that builds it, proves
measure is untouched, and makes the first pictures and numbers. Every flag
below was read from the script it belongs to on the branch. Where a script
was not on the branch yet, this file says so.

- Branch: `claude/vibrant-gauss-olema4`. The base commit, before any look
  work, is `355dae64`.
- What was built, phase by phase: `docs/VISUAL_FIDELITY_PLAN.md` §8.
- Each lane's decisions, constants and probes: `docs/visual/PROBE_LOG.md`.
- The short paste-in version of this file: `docs/visual/WINDOWS_JOB.md`.

Run everything in PowerShell from the repo root unless a step says Git
Bash. `$py` is the repo's own interpreter:

```powershell
$py   = ".\.venv\Scripts\python.exe"
$ue   = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.7" }
$ed   = Join-Path $ue "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$proj = (Resolve-Path ".\ue\FlightSim.uproject").Path
```

Rules that hold for every step:

- Google tiles are the ground of every terrain render. Never set
  `FLIGHTSIM_GOOGLE_TILES=off`. A render that cannot draw the tiles refuses
  by name, and that refusal is the finding.
- The storm weather stays on by default (`webapp/runs.py
  weather_backend_flags`). Do not turn it off to make a shot easier.
- Labels must match pixels. A beauty run that fails `look.*` in
  `flightsim.verify` is a finding, never something to work around.
- Physics is unchanged. If a measure frame or a Gate 6 number moves, stop
  and report it. Do not re-tune anything to make it pass.
- No schedules, no PR or CI polling, no ruflo daemon. Report once at the
  end.

## 0. Before you start

1. The tree is clean: `git status` shows nothing to commit. `runs\` is
   git-ignored, so earlier renders are safe.
2. Cesium for Unreal is installed for the pinned engine. The Mac's only
   `check_bridge_api.sh` FAIL was `module CesiumRuntime`; here it must pass.
3. **Gate 6 deletes the `frame_*.png` files under its `--out` folders.**
   If the decision-25 substitute still (the 6 October frame) lives under
   `runs\gate6\`, copy it out first, for example to
   `runs\gate6_substitute\`, and use that copy as `--substitute-baseline`
   below. If `~\FlightScene\renders` has real old footage, drop the
   `--substitute-baseline` argument everywhere.
4. Make sure `ffmpeg` is on PATH (the clip falls back to it) and the GPU
   supports hardware ray tracing (the path tracer refuses without it).

## 1. Get the branch

```powershell
git fetch origin
git checkout claude/vibrant-gauss-olema4
git pull --ff-only
$head = git rev-parse HEAD
$head
```

The Mac session did not push. If `git checkout` cannot find the branch, the
owner has to push it from the Mac first. Nothing else in this file works
without it.

## 2. API check before spending a build (Git Bash)

```bash
UE_ROOT="/c/Program Files/Epic Games/UE_5.7" bash scripts/check_bridge_api.sh
```

Expect every line to be `ok`, including `module CesiumRuntime` and these
blocks: "render-path lane", "world lane", "engine surface the beauty look
assumes" and "AIRCRAFT LANE". A FAIL means the source is out of step with
the engine. Fix that first, because a build cannot fix it.

## 3. The baseline at the base commit `355dae64`

The base commit has the earlier V0 beauty path but none of this session's
look work. It also has no contact-sheet script, so this step borrows HEAD's
script, plus HEAD's `gate6_visual.py` for the edge-aliasing function the
sheet imports. Neither file changes what the base commit renders.

```powershell
git checkout --detach 355dae64
.\scripts\build_ue.ps1

# Gate 6 under measure at the base: the reference for step 6
& $py experiments\gate6_visual.py --out runs\gate6_base --substitute-baseline runs\gate6_substitute

# the four baseline shots (beauty as the base commit knew it)
git restore --source=$head --worktree -- experiments/visual_contact_sheet.py experiments/gate6_visual.py
& $py experiments\visual_contact_sheet.py --step base --quality beauty
& $py experiments\visual_contact_sheet.py --step base_measure --quality measure

# put the base tree back exactly, then return to the branch
git restore -- experiments/gate6_visual.py
Remove-Item experiments\visual_contact_sheet.py
git status          # must be clean
git checkout claude/vibrant-gauss-olema4
```

Outputs: `runs\visual\base\{a,b,c,d}.png`, `shots.json` (it records commit
`355dae64` per shot) and `sheet.png`. **Open the PNGs and look at them.**
Write down bluntly what makes each one look fake (flat light, plastic
aircraft, smeared ground, empty horizon, aliasing, no clouds, bad
exposure). If the borrowed script fails against the base web app, record
the error in `docs/visual/PROBE_LOG.md` under a `## render-machine`
heading. Fall back to `--quality measure` only, and say so in the record.

## 4. Build HEAD

```powershell
.\scripts\build_ue.ps1
```

This is the first compile of `FlightSimBeautyLook.cpp`, `FlightSimClouds.cpp`,
`FlightSimGroundDetail.cpp`, `FlightSimAircraftFX.cpp` and the commandlet
changes. Ordinary C++ errors are expected on a first compile. Fix them in
small commits and keep every fix behind `-quality=beauty`.

## 5. Re-run the material script, then the aircraft look instances

`ue_create_materials.py` skips assets that already exist. The new ones
are `MPC_FlightSimWorld`, `M_FlightSimCloudLayers`,
`M_FlightSimTilesBeauty` and `/Game/FlightSim/Aircraft/M_Aircraft*`. This
is the same command `scripts\launch_windows.ps1` step 4 uses. Run it by
hand, because the launcher's stamp can say "fresh" without knowing about
the new materials.

```powershell
& $ed $proj -run=pythonscript "-script=$((Resolve-Path scripts\ue_create_materials.py).Path)" -unattended -nopause -nosplash -stdout -FullStdOutLogOutput
#   expect MATERIAL-CREATED for the four names above, and no MATERIAL-FAILED
& $py scripts\launch_check.py materials --stamp

& $ed $proj -run=pythonscript "-script=$((Resolve-Path scripts\ue_fix_aircraft_materials.py).Path) J11 B747 A320 c172p DHC6 p51d A4" -unattended -nopause -nosplash -stdout -FullStdOutLogOutput
#   writes /Game/Aircraft/<NAME>/Look/MI_* and assets\generated\<NAME>\look_manifest.json;
#   read runs\fix_aircraft_materials.txt for LOOK-PROBLEM lines
```

To rebuild one material after a fix, for example the tiles material whose
Cesium parameter names are unverified, set
`$env:FLIGHTSIM_REBUILD_MATERIALS = "M_FlightSimTilesBeauty"` and re-run
the first command.

## 6. Gate 6 under measure: it must be unchanged

```powershell
& $py experiments\gate6_visual.py --substitute-baseline runs\gate6_substitute
#   writes runs\gate6\ and runs\gate6\aliasing.json
& $py experiments\gate10_render_repro.py --against runs\gate6_base\full runs\gate6\full --out runs\visual\gate6_measure_repro
```

All three must hold:

- Gate 6 passes the same clauses it passed at the base, with the same
  numbers to the precision it prints.
- Gate 10-R's verdict on the base frames against the HEAD frames is
  `bit-identical`, or `bounded` within what Gate 10-R already measured
  between two runs of one build.
- `runs\gate6\full\render.json` has **no** `aircraft_look` key, **no**
  `render_settings.beauty_path`, and **no** `look_applied.world_beauty`.

If any of them fails, measure was altered. Stop there and report it; that
is the most important finding this runbook can produce.

Then Gate 6 under beauty, reported and never a gate:

```powershell
& $py experiments\gate6_visual.py --quality beauty --aliasing-baseline runs\gate6 --substitute-baseline runs\gate6_substitute
```

Read `runs\gate6_beauty\full\render.json`:

- `render_settings.beauty_path`: `temporal_aa_show_flag` should be true;
  also read `cvars_read_back` and `scalability_applied`.
- `look_applied.world_beauty`: `tiles.material_route`,
  `tiles.generate_smooth_normals`, `tiles.tileset_properties`.

The `[info]` edge-aliasing change should be negative.

## 7. The contact sheet at HEAD

`scripts\render_visual_sheet.ps1` takes `-Step -Quality -StillSamples
-PathTrace -Spp -Clip -SkipRender -Compare -Shots`. It wraps
`experiments\visual_contact_sheet.py`, which drives the web app's own
handlers, so the tiles and the storm weather behave as they do on the page.

```powershell
.\scripts\render_visual_sheet.ps1 -Step head
.\scripts\render_visual_sheet.ps1 -Step head_measure -Quality measure
.\scripts\render_visual_sheet.ps1 -Step head_ss32 -StillSamples 32 -Shots a
```

Open `runs\visual\head\sheet.png` and the four PNGs, and look at them
against the base list from step 3. In each beauty run's
`frames\...\render.json`, read:

- `beauty_look`: `applied.exposure.applied` should be `"yes"`, and
  `applied.camera.fov_deg_unchanged` should equal the manifest's FOV;
- `aircraft_look`: `slots_applied` and `slots_absent`;
- `look_applied.world_beauty.frames[].cloud_occludes_aircraft`.

A white tiles frame means the Cesium base-colour names are wrong (see
step 5).

## 8. The compare sheet into `runs\visual\final\`

```powershell
.\scripts\render_visual_sheet.ps1 -Compare base,head
New-Item -ItemType Directory -Force runs\visual\final | Out-Null
Copy-Item runs\visual\compare_base_vs_head.png runs\visual\final\
Copy-Item runs\visual\head\sheet.png runs\visual\final\head_sheet.png
Copy-Item runs\visual\base\shots.json runs\visual\final\base_shots.json
Copy-Item runs\visual\head\shots.json runs\visual\final\head_shots.json
```

`--compare` writes `runs\visual\compare_<A>_vs_<B>.png` and has no output
flag of its own, so the copy is what puts it in `final\`.

## 9. The chase clip

```powershell
.\scripts\render_visual_sheet.ps1 -Step final_clip -Shots a -Clip
Copy-Item runs\visual\final_clip\clip.mp4 runs\visual\final\chase_clip.mp4
```

This renders shot a (the J-11 chase over the Matterhorn at golden hour)
as a 15 s beauty clip; `--clip-seconds` accepts 10 to 20. The clip comes
from the web run's own encode, or from the frames through ffmpeg. If
`shots.json` says "no clip: no web encode and no ffmpeg", put ffmpeg on
PATH and re-run. Watch it for breathing exposure, TSR ghosting behind
the moving silhouette (`accumulation.history_across_frames`), strobe
timing and the rain.

## 10. `flightsim.verify` on a labelled beauty render

The contact-sheet shots are real web runs. Take shot a's run folders from
the two HEAD steps:

```powershell
$beauty  = (Get-Content runs\visual\head\shots.json -Raw | ConvertFrom-Json).shots.a.run_dir
$measure = (Get-Content runs\visual\head_measure\shots.json -Raw | ConvertFrom-Json).shots.a.run_dir
Get-ChildItem "$beauty\frames" -Recurse -Filter "frame_*_mask.png" | Select-Object -First 1
& $py -m flightsim.verify $beauty
```

The run needs label masks. If the `Get-ChildItem` line finds no
`_mask.png`, the shot was not labelled. In that case, use the verifier
lane's route (`docs/visual/PROBE_LOG.md`, "verifier-tooling"): start the
web app with `$env:FLIGHTSIM_RENDER_QUALITY = "measure"`, capture a card
with labels on, stop the server, then capture the SAME card with
`"beauty"`:

```powershell
& $py -m uvicorn webapp.server:app --port 8008
```

The verify must end in exit code 0. `look_record` must PASS.
`look_label_alignment` stays NOT RUN until the commandlet writes
`pixel_moving_effects` and `cloud_occlusion`. Once it does, it must PASS.
Any `look.*` refusal is the finding.

## 11. `experiments/look_label_check.py`

```powershell
& $py -m experiments.look_label_check --measure $measure --beauty $beauty --camera chase --out runs\visual\final\look_label_check.json
```

Exit 0 means ALIGNED, 1 means NOT ALIGNED, 2 means VOID (the 3 px control
was not recovered). Record the offsets in `docs/visual/PROBE_LOG.md`
before you change any of its constants.

## 12. Gate V: `experiments/gate_v_visual.py`

Another lane is adding this script. **It was not on the branch when this
runbook was written**, so its flags are not listed here. Do not guess
them:

```powershell
& $py experiments\gate_v_visual.py --help
```

Run it on the HEAD renders the way its help and docstring say. Every
clause needs its self-validation control to trip, otherwise the pass is
void (§5). If the script is still missing, record "Gate V: no script" and
go on.

## 13. The path-traced hero still

```powershell
.\scripts\render_visual_sheet.ps1 -Step head_pt -PathTrace -Spp 256 -Shots a
Copy-Item runs\visual\head_pt\a.png runs\visual\final\hero_pathtrace_a.png
```

`-PathTrace` adds `-quality=pathtrace` and the one-process
`-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=True` override
to the per-camera pass only. `-Spp` accepts 1 to 16384, and
`-StillSamples` cannot be combined with it. The first run compiles the
ray-tracing shaders and is slow. It refuses by name (`render.pathtrace`)
without hardware ray tracing, or when `IsRayTracingEnabled()` stays false
under the override, which is an open risk. Read
`render_settings.beauty_path.path_tracer` and
`accumulation.captures_per_frame`, because exposure changes can reset
the accumulation. The denoiser plugins (NNEDenoiser, OpenImageDenoise)
are not enabled in `FlightSim.uproject`, so expect noise at 256 spp. For
a convergence series, try 64 and 1024.

## 14. Uncalibrated constants: sweep these first

Every look constant was chosen without a frame. Sweep them in this order.
Exposure and sun come first, because every later probe is judged under
them (§4: never calibrate materials under the old exposure).

1. **Checks before sweeps** (each is a yes or no read from `render.json`):
   - TSR on: `beauty_path.temporal_aa_show_flag`;
   - Lumen inside the capture: `cvars_read_back`;
   - tiles not white: the Cesium names `baseColorTexture` and
     `baseColorFactor`, set in `CESIUM_BASE_COLOUR_*` in
     `scripts/ue_create_materials.py`.
2. **`UE_ZENITH_TRANSMITTANCE` (0.90)**, `core/scene/beauty_look.py`. It
   sets the sun lux of every beauty frame. Probe: a `-calibration` white
   quad, sky atmosphere on and then off, sun at 50 degrees; take the ratio
   of the two quad luminances.
3. **`EV100_BANDS` (15.0 / 14.7 / 14.2 / 13.4 / 12.6)**, same file. Probe:
   one clip per band; the sunlit grey card should sit at about 18% of white
   after the tonemapper, with the sky unclipped. No rebuild is needed:
   rewrite a run's `beauty_look.json` (PROBE_LOG look-dev, step 3) and
   re-run that run's commandlet line from its `render.log`.
4. **`look_label_check` `EDGE_PERCENTILE` (80), `CONTROL_SHIFT_PX` (3),
   `CONTROL_SLACK_PX` (1.0)**. Set these on the measure chase frame before
   trusting any ALIGNED or NOT ALIGNED verdict.
5. **World atmosphere: `ATMOSPHERE[*].mie_share`, `mie_cap_per_km`,
   `aerial_perspective_scale`**, `core/scene/world_beauty.py`. Probe:
   far-ridge contrast at 10 and 30 km against Koschmieder for the card's
   visibility. Sweep these without a rebuild through
   `$env:FLIGHTSIM_WORLD_BEAUTY_OVERRIDES = "<abs path>\probe.json"`, for
   example `{"atmosphere": {"clear": {"mie_share": 0.4}}}`;
   `world_beauty.overridden` records what was swept.
6. **Render path: `RenderBeautyStillSamplesDefault` (8),
   `RenderBeautyTsrHistorySamples` (32),
   `RenderBeautyTsrHistoryScreenPercentage` (200)**, in
   `FlightSimRenderCommandlet.cpp`. These need a rebuild. Probe: shot a's
   edge aliasing at `-StillSamples 1`, `8` and `32` (step 7 already made
   the 32).
7. **`tiles_dehaze`, `tiles_saturation`, `tiles_detail_strength`**: a clear
   noon nadir frame and a 300 m AGL chase frame (overrides as in item 5).
8. After those: `rain_readability_gain`, the `CLOUDS[*]` table (rendered
   cloud fraction against card cover within 15%), the `GRADES`, the
   `LENSES`, and the aircraft class scalars and lights (V7 side by side
   against a reference photo, the reader's judgment, labelled as such).

Record every probe result in `docs/visual/PROBE_LOG.md` under a
`## render-machine` heading, and in ruflo memory under namespace `visual`
with key `visual-overhaul/render-machine/<topic>`, before you change a
constant. Commit the changes in small steps with real messages. Push the
branch, open one draft PR, report once, and stop.
