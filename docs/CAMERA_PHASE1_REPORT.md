# Camera Phase 1 — Camera Control and Capture Geometry: report

What was implemented, how to demonstrate it, and what remains. Written
against the phase plan ("Phase 1 — Camera Control and Capture
Geometry") as it landed on this tree.

## What the camera is now

Before this phase the camera was a render-time preset: chosen by the
webapp (`-camera=` / `-chase=` flags, hardcoded per airframe), computed
per-frame in C++, absent from the spec, the digest and the review
table. Now:

* **The camera is a spec element** (`core/scenario/camera.py`,
  `SPEC_VERSION` 6). Every field is a provenanced `Quantity` (user >
  inferred > model > derived > default); cameras serialize canonically,
  enter the digest, render in the review table as labeled editable
  blocks, and are addressable through the same `set()`/`plan()` front
  door (`cameras[0].focal_length_mm`). A user-stated camera field is
  never silently moved — `plan()` refuses by name. Version-5 specs
  refuse by the named version error; completed runs recover from
  `provenance.json`, never by re-parsing.
* **No camera stated == exactly the old behaviour.** `default_cameras`
  returns the documented default (the webapp chase offsets per
  airframe; the measured wingman rule for through-the-core tornado
  runs), and a test pins the commandlet argument list for a camera-less
  spec byte-identical against the real command builder
  (`tests/test_camera_spec.py`).
* **Pose tracks are computed in Python and consumed verbatim**
  (`core/capture/poses.py`) — the run-card discipline. The five UE
  presets are ported faithfully (heading-only offset frames for
  chase/wingman, world-anchored ground/tower with aim lag, body-fixed
  cockpit with roll inherited BY DECLARATION — `horizon_stable` mirrors
  `PresetKeepsHorizonLevel()`), plus `explicit` placement in scene
  metres or geographic coordinates with keyframed moves (linear
  position/focal, slerp aim). Deterministic: no wall clock, no RNG, no
  frame-rate dependence; bit-identical re-invocation and cross-rate
  keyframe agreement are pinned by digest tests.
* **Capture schedules are functions of telemetry only**
  (`core/capture/schedule.py`): exact image counts (endpoints
  included), periods snapped to the sample clock, waypoint distance
  along the flown projected track, proximity, and channel-event
  triggers with a refractory period. A stated count is a contract:
  exactly that many frames or a named `camera.schedule` refusal.
* **Validation refuses by name** (`core/capture/validate.py`, riding
  the existing `Violation` surface): `camera.intrinsics`,
  `camera.preset`, `camera.schedule` scene-free in core `validate()`;
  `camera.terrain_clearance` (whole solved track against the raster),
  `camera.scene_bounds`, `camera.hazard_intersection` (the modelled
  tornado core — one shared placement helper with the card blocks)
  scene-coupled in `/run` and the CLI, the `plan_terrain_flight`
  pattern.
* **Every run writes `capture_manifest.json`**
  (`core/capture/manifest.py`, `manifest_version` 1, schema in the
  module docstring): per frame the pose (position, quaternion AND
  Euler), full intrinsics (focal, sensor, principal point, pixel focal
  lengths, near/far), the relative per-camera image path, and the
  aircraft state at that instant; per run the spec digest, the
  camera-free `simulation_digest`, the telemetry `output_digest`, the
  seed, the terrain raster SHA-256, the scene-frame CRS and the git
  revision.
* **Verification can fail** (`core/capture/verify.py`): temporal
  alignment across camera variants, geometry recovery through an
  independent reprojection (quaternion cross-checked against Euler;
  aimed cameras must contain the aircraft), two-view triangulation
  (each ray cast through its own record's view, so misattribution
  breaks it — the circular formulation is documented and avoided), and
  count exactness. Each check is demonstrated to fail on a corrupted
  manifest, and `scripts/mutation_check.sh` gained 19 guards, each
  verified to fail its test when its safeguard is disabled.
* **The prompt surface expresses cameras** (`core/nl/compiler.py`,
  `core/nl/llm_compiler.py`): named views, image counts, lens words
  with documented mm mappings; a bounded provenanced `cameras` block in
  the LLM response schema with the same strict rails, tied to
  `CameraSpec`'s field list by an import-time assert; one camera-intent
  clarifying question allowed under the existing caps; five camera
  prompts added to the Gate 8 corpus.

## How to demonstrate (any platform)

```bash
.venv/bin/pytest -q                        # full suite incl. tests/test_camera_*.py
./scripts/mutation_check.sh                # all guards, incl. the 19 new ones

.venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo
.venv/bin/python -m flightsim.verify runs/demo
```

Expected off macOS: validation passes, the headless run flies, 48
frames (24 per camera) are scheduled, `capture_manifest.json` +
geometry previews are written, verification reports 5/5 PASS — and the
pixel render refuses BY NAME (`ue.platform`), which is the designed
outcome, not a failure. On macOS the same command additionally has the
render half available (see "engine boundary" below).

Also committed:

* `examples/cameras_waypoint.yaml` — waypoint capture each 400 m of
  flown track (open loop; add `--terrain <bake>` over a real raster);
* `examples/cameras_refusal.yaml` — a camera stated 600 m under the
  terrain datum; expected outcome
  `REFUSED [camera.terrain_clearance]`, named in the file header.

Temporal alignment across camera sets is exercised on real telemetry by
`tests/test_camera_cli.py::test_two_camera_sets_align_in_time`: the
same spec captured with a chase+tower set and again with a cockpit set
aligns frame-for-frame (`flightsim.verify --against`).

## The engine boundary (what was NOT verified here)

Rendering stays behind `core/util/platform.ue_available()` and the
named `ue.platform` refusal. The engine-consumption half (package G) is
**additive and deliberately thin on this branch**:

* `write_run_card` accepts an optional `cameras` block (spec fields +
  solved per-sample pose tracks + capture times + the projected
  origin), computed in Python, consumed verbatim.
  `python -m flightsim.capture ... --card` writes it
  (`PoseTrack.card_block`), so an off-mac machine produces everything a
  render-capable one consumes.
* The C++ consume-poses mode is implemented additively and mirrors the
  existing card-block style: `FlightSimCameraDirector::SetPoseTrack` /
  `ApplyPoseAtTime` interpolates the card's track (linear position,
  slerp rotation), REFUSES a track that does not cover the run (never
  extrapolates), and fails loudly when the applied pose differs from
  the solved one beyond 10 cm; the render commandlet reads the card's
  `cameras` block itself (`-camera-index=N`, one invocation per camera
  with its own `-frames=` directory), places poses through the
  plugin's own `ProjectedToEngine` + yaw−90 mapping, and adds
  ASCII-only applied-pose fields to `render.json` (gotcha 13). Preset
  cards without the block fly byte-identically.
* **These C++ changes could not be compiled or run in this
  environment** (no macOS, no engine; `scripts/check_bridge_api.sh`
  output is unchanged by them, engine-absent failures aside). The
  verification step for a macOS session: build via
  `scripts/build_ue.sh`, run
  `python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo --card`,
  render `runs/demo/card.json` once per camera with `-camera-index=N`,
  and grade the frames against `capture_manifest.json`: the
  commandlet's own applied-vs-solved parity must stay silent, and the
  aircraft must project into each frame where
  `core/capture/verify.py`'s reprojection says it should.

## Known limitations

* Keyframed moves only — no physically simulated camera platforms (out
  of scope by the phase definition).
* The headless CLI's tornado hazard check uses the straight-line
  45%-ahead placement (its own track IS straight); the webapp's
  terrain runs refine the placement onto the pre-flown banked track
  through the same shared helper.
* Cross-view consistency is honestly reported NOT EXERCISED for
  single-camera runs (no false pass, no false failure).
* Segmentation masks, bounding boxes, domain randomization, batch
  execution: out of scope, untouched.
