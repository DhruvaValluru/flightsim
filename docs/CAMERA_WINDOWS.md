# Camera capture on Windows

The supported path, end to end, and what each step actually proves.

## Setup

```powershell
git clone https://github.com/DhruvaValluru/flightsim.git
cd flightsim
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

That gets you everything except pixels. For pixels you also need Unreal
Engine 5.5 and a built bridge:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ue_preflight.ps1   # names anything missing
powershell -ExecutionPolicy Bypass -File scripts\build_ue.ps1
```

## Capture

```powershell
.\.venv\Scripts\python.exe -m flightsim.capture examples\cameras_multi.yaml --out runs\demo --render
.\.venv\Scripts\python.exe -m flightsim.verify runs\demo
```

`--render` implies `--card` and drives `scripts\render_ue_scenario.ps1`,
which runs **one commandlet pass per camera** into
`runs\demo\frames\<camera_id>\`. Without the engine, drop `--render`:
everything except the pixels still runs, and the `ue.platform` refusal
names what is missing.

### What lands on disk

| path | what it is |
| --- | --- |
| `capture_manifest.json` | every frame's camera pose, full intrinsics, the aircraft state at that instant, and the scene's known landmarks |
| `telemetry.json` | the recorded flight the poses were solved over |
| `card.json` | the run card the commandlet consumes: solved pose tracks, intrinsics, landmarks |
| `frames\<camera_id>\` | the rendered PNGs, plus `render.json` |
| `overlays\<camera_id>\` | the recorded geometry drawn **on** the rendered pixels |
| `previews\<camera_id>\` | the engine-free geometry preview (fallback) |

## What to look at, and what it proves

**The overlays are the thing to look at first.** Each one draws the
manifest's own projection of every landmark as a **circle** and the
engine's own `ProjectToPixel` output for the same landmark as a
**cross**. Two implementations, in two languages, of the same
projection. When they coincide there is one symbol per landmark. When
they do not, the gap you see *is* the error, at the scale it actually
is. The aircraft crosshair should sit on the rendered aircraft and the
white horizon line along the rendered horizon.

That is the check the phase exit criterion asks for, and it is the one
thing a manifest alone can never establish: projecting a point out of a
manifest and back-projecting it through the same numbers returns the
point you started with, whatever those numbers are.

**Then read the verification summary.** It reports three statuses, and
NOT RUN is not a pass:

```
  [PASS]    intrinsics_match_spec        the lens is the one the spec asked for
  [PASS]    pose_matches_spec            the track is the camera the spec asked for
  [PASS]    geometry_recovery            the aircraft is in the frames that claim it
  [PASS]    landmark_reprojection        Python's projection == the engine's
  [PASS]    cross_view_consistency       a landmark seen twice triangulates back
  [PASS]    count_exactness              exactly the images the spec requested
  [PASS]    aircraft_state_consistency   the manifest agrees with itself
  [NOT RUN] temporal_alignment           needs a second run: --against <dir>
```

Off Windows, or before the engine is built, `landmark_reprojection` and
`cross_view_consistency` report NOT RUN, because their reference is the
engine. The other checks still run and can still fail: their reference
is the specification, which is an input to the solver rather than an
output of it.

## Temporal alignment

Two captures of the same simulation with different cameras must produce
frame sets that align exactly in time:

```powershell
.\.venv\Scripts\python.exe -m flightsim.capture examples\cameras_multi.yaml --out runs\a
.\.venv\Scripts\python.exe -m flightsim.capture examples\cameras_waypoint.yaml --out runs\b
.\.venv\Scripts\python.exe -m flightsim.verify runs\a --against runs\b
```

## Refusals

```powershell
.\.venv\Scripts\python.exe -m flightsim.capture examples\cameras_refusal.yaml --out runs\refused
```

Expected: `REFUSED [camera.terrain_clearance]` — a camera placed under
the terrain. The other named camera refusals are `camera.scene_bounds`,
`camera.hazard_intersection`, `camera.intrinsics`, `camera.schedule`,
and, on the engine side, `camera.applied_divergence` when the pose the
engine applied differs from the solved one.

## Known limits

* **The C++ in this change has not been compiled.** It was written on a
  Linux machine with no engine. `scripts\build_ue.ps1` is the first
  real test of it; if the bridge fails to build, that is this change,
  not your machine.
* **The web UI renders one camera.** It drives the commandlet's preset
  machinery, not the solved pose track, and now refuses by name
  (`camera.multi_render`) rather than silently rendering the first
  camera of a multi-camera spec. Multi-camera capture is the CLI's.
* **The render still re-flies the scenario.** `flightsim.capture` flies
  headlessly to solve the poses, and the commandlet flies again to
  render. If the host's flight is not bit-identical to the headless
  one, the manifest labels a slightly different flight than the frames
  show. The overlays make any such divergence visible — the crosshair
  drifts off the aircraft — and closing it properly is the next step
  (`docs/CAMERA_PHASE2_WINDOWS_PLAN.md`, "One flight, not two").
* Segmentation masks, bounding boxes, domain randomization and batch
  execution remain out of scope.
