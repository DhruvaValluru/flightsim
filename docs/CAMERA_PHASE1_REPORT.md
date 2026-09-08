# Camera Phase 1 — Camera Control and Capture Geometry: report

What was implemented, how to demonstrate it, and what remains. Written
against the phase plan ("Phase 1 — Camera Control and Capture
Geometry") as it landed on this tree.

> **Corrections, 2026-09-08.** An adversarial review measured three
> claims below to be wider than the evidence, and found the phase's own
> exit criterion unable to fail. See `docs/CAMERA_PHASE1_GRADE.md` for
> the grade, the measurements and the repairs; the corrections are
> folded into the text below rather than left standing.

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
  position/focal, slerp aim). Deterministic: no wall clock, no RNG;
  bit-identical re-invocation is pinned by digest test. **Frame-rate
  independence is KEYFRAME-ONLY**: the `explicit` preset's keyframed
  solution is a continuous function being sampled and agrees exactly
  across rates (pinned by test), but the LAGGED presets are an
  exponential filter driven by a moving goal and do not -- measured
  1.68 m of chase-camera disagreement between a 10 Hz and a 20 Hz solve
  of the same flight. Bounded, documented, and a follow-up (grade doc,
  finding 1).
* **Capture schedules are functions of telemetry only**
  (`core/capture/schedule.py`): exact image counts (endpoints
  included), periods snapped to the sample clock, waypoint distance
  along the flown projected track, proximity to a stated coordinate,
  and channel-event triggers with a refractory period. (Proximity was
  implemented and tested here from the start but missing from the
  spec's `TRIGGER_KINDS`, so every specification naming it refused as
  an unknown trigger: the tests called the scheduler directly and
  exercised a path no run could take. Reachable now, with tests that go
  through validation and a YAML round-trip.) A stated count is a
  contract:
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
* **Verification can fail** (`core/capture/verify.py`). The original
  four checks — alignment, geometry recovery, two-view triangulation,
  count exactness — read the manifest AGAINST ITSELF, and measurement
  showed all of them passing on a manifest whose camera was displaced
  500 m and re-aimed, whose focal length was multiplied by 1.7, and
  which delivered 10 of 24 requested images. Independent *code* is not
  independent *evidence*. Four external-anchor checks now read the
  manifest against artefacts the camera code did not author:
  `intrinsics_match_spec` (fx, fy and principal point recomputed from
  the recorded camera specification), `placement_matches_spec` (world
  anchors exact, offset cameras inside a stated lag envelope),
  `telemetry_agreement` (every frame's time and aircraft state against
  `telemetry.json` at the sample index it names), and `engine_parity`
  (a render manifest's applied pose AND field of view against the
  solved one). `count_exactness` now compares against the count the
  SPECIFICATION requested rather than the one the producer wrote down.
  Every corruption above trips. `scripts/mutation_check.sh` carries 29
  camera guards, each verified to fail its test when disabled.
* **The prompt surface expresses cameras** (`core/nl/compiler.py`,
  `core/nl/llm_compiler.py`): named views, image counts, lens words
  with documented mm mappings; a bounded provenanced `cameras` block in
  the LLM response schema with the same strict rails, tied to
  `CameraSpec`'s field list by an import-time assert; one camera-intent
  clarifying question allowed under the existing caps; five camera
  prompts added to the Gate 8 corpus.

## How to demonstrate (any platform)

```bash
./scripts/verify_phase1.sh                 # THE single command (Windows: .ps1)

.venv/bin/pytest -q                        # full suite incl. tests/test_camera_*.py
./scripts/mutation_check.sh                # all guards

.venv/bin/python -m flightsim.demo         # capture twice, verify all three properties
.venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo
.venv/bin/python -m flightsim.verify runs/demo

# over a real raster, no network and no account:
.venv/bin/python -m flightsim.capture examples/cameras_terrain.yaml \
    --out runs/terrain --synth-terrain
```

The web app delivers the same artefacts on every platform:
`POST /run` returns 200 with `render_refused` naming the pixel refusal,
and the run writes its manifest and previews and reports its
verification on the page (`GET /runs/<id>/capture_manifest.json`,
`/verify`, `/previews/<camera>/<file>`).

Expected off a render-capable machine: validation passes, the headless
run flies, 48 frames (24 per camera) are scheduled,
`capture_manifest.json` + geometry previews are written, verification
reports 8/8 PASS — and the pixel render refuses BY NAME
(`ue.platform`), which is the designed outcome, not a failure. On a
render-capable machine the same command additionally has the render
half available (see "engine boundary" below).

Also committed:

* `examples/cameras_waypoint.yaml` — waypoint capture each 400 m of
  flown track (open loop; add `--terrain <bake>` over a real raster);
* `examples/cameras_refusal.yaml` — a camera stated 600 m under the
  terrain datum; expected outcome
  `REFUSED [camera.terrain_clearance]`, named in the file header;
* `examples/cameras_terrain.yaml` — the waypoint capture the phase asks
  for OVER REAL TERRAIN, with `--synth-terrain`: a deterministic raster
  centred on the spec's own origin, no network and no account (the
  first two examples ran on a flat scene, so "over real terrain" was
  not what they showed);
* `examples/cameras_mountain_refusal.yaml` — the refusal case the phase
  asks for: a camera stated 545 m INSIDE the ridge, refused against the
  RASTER rather than against a flat datum.

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
* The engine consumes the INTRINSICS as well as the pose. It did not:
  `Capture->FOVAngle` was hardcoded at 55 deg (visual) / 24 deg (void)
  and the output at 1280x720, while the manifest recorded fx from the
  specification's own lens and sensor. On the default camera that is
  7.8 px of disagreement at the frame edge, fifteen times this phase's
  own 0.5 px tolerance; on a stated 85 mm telephoto the recorded
  geometry would have been wrong by a factor of 2.5 — the "plausible
  fiction" this phase names as its second risk, with the parity check
  pointed at the wrong half of the pose. The commandlet now reads
  `width_px`, `height_px`, `sensor_width_mm` and the per-sample
  `focal_length_mm` from the card and refuses a block without them, and
  `ApplyPoseAtTime` checks orientation parity (0.05 deg) as well as
  position.
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
  single-camera runs (no false pass, no false failure) — and remains
  partly self-referential even when exercised, since each ray is cast
  through a pixel that camera's own record produced. The external
  anchors constrain the poses and the aircraft states around it; a
  scene-provided point (a summit, a threshold) would close it properly.
  Only the first two cameras of a shared instant are triangulated.
* The prompt surface is roughly one third of package F: multi-camera
  prompts, keyframed move phrases, and every waypoint/event trigger
  word are absent from both compilers. Measured, with reproductions, in
  the grade doc (finding 2).
* Segmentation masks, bounding boxes, domain randomization, batch
  execution: out of scope, untouched.
