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

`--render` flies the card in the host **first** — the telemetry-only
commandlet, no renderer — and re-solves every pose over *that* flight
before rendering, so the aircraft labels describe the flight the pixels
show ("One flight, not two" below). `--no-host-flight` skips that pass.
`--render` implies `--card` and drives `scripts\render_ue_scenario.ps1`,
which runs **one commandlet pass per camera** into
`runs\demo\frames\<camera_id>\`. Without the engine, drop `--render`:
everything except the pixels still runs, and the `ue.platform` refusal
names what is missing.

### What lands on disk

| path | what it is |
| --- | --- |
| `capture_manifest.json` | every frame's camera pose, full intrinsics, the aircraft state at that instant, the scene's known landmarks, and `solve_source` -- which flight those aircraft states came from |
| `host_flight\host_telemetry.json` | the flight the host flew for the poses to be solved over (absent with `--no-host-flight`) |
| `telemetry.json` | the headless pre-run: the validation flight, and the solve source only under `--no-host-flight` |
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
  [PASS]    host_determinism             every host flight of one card was identical
  [PASS]    capture_time_agreement       the pixels are from the instant they claim
  [NOT RUN] temporal_alignment           needs a second run: --camera-sets, or --against <dir>
```

Measured on `examples\cameras_multi.yaml`, so you know what "PASS"
is worth here: landmark reprojection agrees with the engine to
**0.00 px** over 916 projections (tolerance 2.0), two-view
triangulation to **0.000 m** over 216 sightings (tolerance 0.5), and the
two render passes flew **byte-identical** flights.

Those figures were taken before the host flew its own solve flight, so
`flight_agreement` read **1.38 m** there, against the 25 m a pre-run
solve is allowed. Measured again on `examples\cameras_terrain.yaml`
with the host flying first: **0.00 m**, against 0.5 m.

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

Type a scenario, then add points of view under the review table:

    Points of view — each one renders as its own commandlet pass, with its
    own frames, overlays and per-frame metadata.
    [+ chase] [+ ground] [+ wingman] [+ tower] [+ cockpit] [+ explicit]

Five modelled views plus `explicit`, which is not a view — it is "I will
state the position myself". Each button appends a camera whose 32 fields
come from `CameraSpec.defaulted` on the server, so the page never invents
a default; each camera then appears as its own editable block with per-
field provenance, and `remove` drops it. Ids are generated distinct
(`chase`, `chase1`, …) because the id names the directory the frames land
in; a stated id is never renamed.

A spec that states cameras is **captured, not clipped**: the host flies
the card first and every pose is solved over that flight, one commandlet
pass per camera, and a gallery under the clip shows the overlays, the
rendered frames and the previews per camera, with the verification
summary and a link to `capture_manifest.json`.

Every view is another engine pass. Six views is one solve pass plus six
render passes, and the page says so before you press Run.

Under each camera in the gallery is **open all N frame(s) with their
metadata →**. That page puts every frame of that one camera beside its
own record — where the camera was, which way it pointed, what lens, and
what the aircraft was doing at that instant — with the overlay, the
rendered frame and the preview for each. Beside it, **this camera's
manifest**: the same thing as JSON, carrying the CRS its metres are in,
the scene and its raster digest, the landmarks, and which flight the
labels were solved over. The whole-run manifest interleaves every
camera's frames in one list, which is what verification wants and not
what a person reading one view wants.

The routes behind it, if you want them directly:

| route | what it returns |
| --- | --- |
| `POST /cameras` | add a view (`{spec, preset}`) or drop one (`{spec, remove}`); returns the whole spec payload |
| `/frames.html?run=<id>&camera=<cid>` | one camera's frames, each beside its own pose, intrinsics and aircraft state |
| `/runs/<id>/cameras/<cid>/manifest.json` | that camera on its own: its block, only its frames, and the CRS/scene/landmarks they need |
| `/runs/<id>/images` | what images exist, per camera and per kind |
| `/runs/<id>/frames/<camera>/<name>.png` | a rendered frame |
| `/runs/<id>/overlays/<camera>/<name>.png` | that frame with the recorded geometry drawn on it |
| `/runs/<id>/previews/<camera>/<name>.png` | the engine-free preview |
| `/runs/<id>/capture_manifest.json` | the labels |
| `/runs/<id>/verify.json` | the verification summary |

## One flight, not two

Poses used to be solved over a **headless pre-run** — the `jsbsim`
Python package — after which the host flew the same card through **UE's
vendored JSBSim**. Two builds stepping one scenario do not agree:
**1.38 m worst at t~1.5 s**, measured. The camera poses survived that
(the host consumes them verbatim) but the `aircraft` block in every
frame record described a flight the frames did not show. For labelled
training data that is the defect that matters: the camera is exactly
where the label says, and the thing in front of it is up to a metre and
a half from where the label says.

`--render` now flies the host **first**:

```
1. fly headless   the cheap pre-flight gate — a camera inside a
                  mountain still refuses BEFORE any engine time
2. fly the host   telemetry-only commandlet, no renderer
                  -> host_flight\host_telemetry.json
3. re-solve       poses, schedules, scene checks, manifest, card,
                  all over the host's own flight
4. render         one pass per camera, consuming those poses
```

What makes step 4 agree with step 2 is that **the host is
bit-deterministic** — measured: two passes over one card, byte-identical
across 30 columns and 120 samples, SHA-256 `4e5a7334...`, worst
per-sample difference exactly 0. The render passes re-fly the identical
flight, so the manifest describes the pixels by construction rather than
to a tolerance.

That is a conditional decision, so it keeps checking its condition.
Every rendered run now records at least two host flights (the solve pass
plus one per camera) and `host_determinism` compares their digests — it
no longer reports NOT RUN on a single-camera render. And
`flight_agreement` reads the manifest's `solve_source`: one claiming a
host solve is held to **0.5 m** rather than 25 m, so a silent fallback
to the pre-run (1.38 m) FAILS by name instead of hiding inside a
tolerance sized for it.

`--no-host-flight` keeps the old behaviour deliberately. It is one
commandlet pass cheaper, and the manifest records which you chose.

**Measured, `examples\cameras_terrain.yaml`, UE 5.5:** the manifest's
aircraft track matches the host's own recorded flight to **0.00 m**
(tolerance 0.5), against **1.38 m** when the poses were solved over the
headless pre-run. And `host_determinism` compared **three** flights of
one card — the solve pass plus both render passes — and found them
byte-identical over 900 samples. The solve pass is given the terrain
flags but not `-Visual`; that it lands bit-identical to two passes that
DID get `-Visual` is the measurement which retires the open question of
whether the render scene perturbs the flight. It does not.

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
* ~~The web app still solves over the pre-run.~~ It no longer does: a
  web run with cameras flies the host to solve over, re-solves every
  camera against that flight, and gives each render pass its own
  `-telemetry=` into `frames\<camera_id>\host_telemetry.json`. Its
  manifest reads `solve_source: "host flight"` and `flight_agreement`
  grades it at 0.5 m like the CLI's. **Not yet measured on Windows** —
  the CLI path is (0.00 m); this one has been exercised only by test.
* ~~The 0.5 m host-solve bound has not been measured on Windows.~~
  **Measured: 0.00 m**, on `examples\cameras_terrain.yaml`, UE 5.5,
  30 frames across two cameras. The bound was reasoned from the
  interpolation residual and is not being approached.
* Segmentation masks, bounding boxes, domain randomization and batch
  execution remain out of scope.
