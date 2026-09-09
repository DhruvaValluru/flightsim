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

Or both, stopping at whichever went wrong and reading the verification's
own verdict rather than the exit code of the last thing it ran:

```powershell
.\scripts\capture_windows.ps1                                          # the demo above
.\scripts\capture_windows.ps1 examples\cameras_terrain.yaml runs\terrain -SynthTerrain
```

### The scene the frames are taken in

Frames render in the **visual scene** — sun, sky, atmosphere, fog, and
terrain when the run has a bake. `-SynthTerrain` (or `--synth-terrain`)
raises a ridge under the scenario's origin, deterministic from its seed
and needing no network, so a clone can produce a landscape immediately;
`--terrain <stem>` uses a real Copernicus bake.

`--void` renders in the black-void tier instead: no sky, no horizon, no
ground, just the lit airframe. That is what the silhouette measurements
want and it is what the camera path used to do unconditionally, which
is why its frames were a grey aeroplane on black.

A camera placed for flat terrain will not survive a ridge, and should
not: `examples\cameras_multi.yaml` puts its tower at 80 m MSL, so over
the synthesised ridge it refuses with `camera.terrain_clearance`
(“requested −2802.8 m AGL”). `examples\cameras_terrain.yaml` is the one
baselined for terrain.

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
  [PASS]    flight_agreement             the manifest labels the flight the host flew
  [PASS]    host_determinism             both render passes flew the same flight
  [PASS]    capture_time_agreement       the pixels are from the instant they claim
  [NOT RUN] temporal_alignment           needs a second run: --camera-sets, or --against <dir>
```

Measured on `examples\cameras_multi.yaml`, so you know what "PASS"
is worth here: landmark reprojection agrees with the engine to
**0.00 px** over 916 projections (tolerance 2.0), two-view
triangulation to **0.000 m** over 216 sightings (tolerance 0.5), the
manifest's aircraft track sits **1.38 m** from the host's own recorded
flight (tolerance 25), and the two render passes flew **byte-identical**
flights.

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
frame sets that align exactly in time — the camera set must not perturb
the simulation or the capture clock. One command does both captures and
grades them:

```powershell
.\.venv\Scripts\python.exe -m flightsim.verify --camera-sets examples\cameras_multi.yaml --out runs\align
```

It splits the spec's own camera list in half and captures once per half,
so the two runs differ in exactly one thing — which cameras were asked
for — rather than in whatever else two hand-written example files
happen to disagree about. Add `--render` to render both. It refuses by
name (`verify.camera_sets`) on a spec with fewer than two cameras, and
on one whose two halves ask for different capture schedules: those
frame sets are not supposed to align, and reporting that as a failure
would be a red light with nothing behind it.

The manual form still works when you have two runs you specifically
want compared:

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

* The plugin's own C++ tests run with `.\scripts\test_ue.ps1`. They
  drive the applied-vs-solved parity tolerances at their boundaries
  and the pose-track refusals; they need the engine but not a GPU.
* **A camera-less run still produces only a clip.** State no camera and
  the run takes the legacy single-pass path, whose commandlet arguments
  are pinned byte-identical by test. Its flat `frames/` are served and
  shown, but there is no manifest and no verification, because nothing
  solved a pose. State a camera to capture.
* **The render still re-flies the scenario.** Poses are solved over a
  headless pre-run, then the host flies the scenario itself. The camera
  poses are consumed verbatim so those are exact; the AIRCRAFT states in
  the manifest come from the pre-run. This is no longer silent, and it
  is no longer unmeasured: `flight_agreement` compares the manifest's
  aircraft track against the host's own recorded telemetry (written per
  camera pass to `frames\<camera_id>\host_telemetry.json`), interpolated
  to each frame's instant, and FAILS beyond 25 m. **Measured: 1.38 m**
  on the demo — the pre-run is the `jsbsim` Python package and the host
  is UE's vendored JSBSim, two builds of one simulator.

  The host itself is bit-deterministic: two passes over one card fly
  byte-identical flights, which `host_determinism` asserts on every
  multi-camera render. So replay is not needed for *reproducibility* —
  but it is still what would close the 1.38 m *agreement* gap. See
  `docs/CAMERA_PHASE2_WINDOWS_PLAN.md`, "The measurement, taken".
* Segmentation masks, bounding boxes, domain randomization and batch
  execution remain out of scope.
