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

## From the web app

The same capture, from the browser:

```powershell
.\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008
```

Type a scenario, add a camera in the review table (or several), and run.
A spec that states cameras is **captured, not clipped**: poses solved in
Python, one commandlet pass per camera, and a gallery under the clip
showing the overlays, the rendered frames and the previews per camera,
with the verification summary and a link to `capture_manifest.json`.

The routes behind it, if you want them directly:

| route | what it returns |
| --- | --- |
| `/runs/<id>/images` | what images exist, per camera and per kind |
| `/runs/<id>/frames/<camera>/<name>.png` | a rendered frame |
| `/runs/<id>/overlays/<camera>/<name>.png` | that frame with the recorded geometry drawn on it |
| `/runs/<id>/previews/<camera>/<name>.png` | the engine-free preview |
| `/runs/<id>/capture_manifest.json` | the labels |
| `/runs/<id>/verify.json` | the verification summary |

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
* **A camera-less run still produces only a clip.** State no camera and
  the run takes the legacy single-pass path, whose commandlet arguments
  are pinned byte-identical by test. Its flat `frames/` are served and
  shown, but there is no manifest and no verification, because nothing
  solved a pose. State a camera to capture.
* **The render still re-flies the scenario.** Poses are solved over a
  headless pre-run, then the host flies the scenario itself. The camera
  poses are consumed verbatim so those are exact; the AIRCRAFT states in
  the manifest come from the pre-run. This is no longer silent: the
  `flight_agreement` check compares the manifest's aircraft track
  against the host's own recorded telemetry, matched on simulation time,
  and FAILS the run's verification when they differ by more than 25 m.
  Closing it properly (replaying the telemetry rather than re-flying) is
  still the next step — `docs/CAMERA_PHASE2_WINDOWS_PLAN.md`, "One
  flight, not two".
* Segmentation masks, bounding boxes, domain randomization and batch
  execution remain out of scope.
