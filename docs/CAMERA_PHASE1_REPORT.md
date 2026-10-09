# Camera Phase 1 — Camera Control and Capture Geometry: report

> **Superseded in part by Camera Phase 2** (`docs/CAMERA_PHASE2_WINDOWS_PLAN.md`).
> Three claims below were wrong and are withdrawn here rather than
> quietly edited, because the corrections are the useful part:
>
> 1. **"the circular formulation is documented and avoided"** — it was
>    documented and then committed. `verify_triangulation` cast both
>    rays through each record's copy of one aircraft array, so they met
>    at that point whatever the poses were. It reported `0.0000 m` and
>    passed with a camera displaced 300 m and with every focal length
>    scaled 1.7x. Two-view consistency now needs independently measured
>    pixels and reports NOT RUN without them
>    (`tests/test_camera_verify_corruption.py`).
> 2. **"Every run writes `capture_manifest.json` ... on every platform"**
>    — it was written by `flightsim/capture.py` and by nothing else. No
>    rendered run produced one, because the web render path never called
>    it.
> 3. **"the UE render half is macOS-only"** — Windows has rendered since
>    `e73aee8`. Windows is now the supported render platform; macOS
>    builds from the same sources and is not the tested path.
>
> Also corrected: the commandlet's field of view was hardcoded (55°)
> rather than derived from the recorded lens, so the manifest's
> intrinsics described an image nobody rendered; `-camera-index` was
> invoked by nothing in the tree; and the geometry preview drew 128
> non-background pixels on a 640×360 canvas.

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
* **Verification** (`core/capture/verify.py`). ~~Each check is
  demonstrated to fail on a corrupted manifest.~~ **Withdrawn.** Four
  of the checks could not fail: triangulation was circular (above),
  geometry recovery compared two encodings of one rotation and only
  ever projected the aircraft, count exactness compared the schedule
  length against the frame list, and the documented verify command
  never ran the alignment check at all. Rebuilt in Phase 2 around what
  each check's independent reference actually is — the specification,
  the engine, or a second run — with a NOT RUN status for the ones
  whose reference is absent.
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

Expected on a machine without the engine (any OS): validation passes,
the headless run flies, 48 frames (24 per camera) are scheduled,
`capture_manifest.json` + geometry previews are written, verification
reports every engine-free check PASS — and the pixel render refuses BY
NAME (`ue.platform`), which is the designed outcome, not a failure. On
Windows with the built host (`docs/CAMERA_WINDOWS.md`) the same command
with `--render` additionally produces the frames per camera.

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
named `ue.platform` refusal — on **Windows**, the render platform, since
`e73aee8`. The paragraphs below are the Phase 1 record as written when
the engine half had not yet run anywhere; Camera Phase 2
(`docs/CAMERA_PHASE2_WINDOWS_PLAN.md`) ran it on Windows and measured
0.00 px landmark reprojection over 916 projections. The
engine-consumption half (package G) was **additive and deliberately thin
on this branch**:

* `write_run_card` accepts an optional `cameras` block (spec fields +
  solved per-sample pose tracks + capture times + the projected
  origin), computed in Python, consumed verbatim.
  `python -m flightsim.capture ... --card` writes it
  (`PoseTrack.card_block`), so an engine-less machine produces
  everything a render-capable one consumes.
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
  environment** (no engine; `scripts/check_bridge_api.sh` output is
  unchanged by them, engine-absent failures aside). The verification
  step, since done on Windows in Camera Phase 2: build via
  `scripts\build_ue.ps1`, run
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

## Gap closure (2026-09-11): every open item of the phase plan, closed

Audited against the phase plan after Phase 10, four items were missing
and three partial. All are closed here, on Windows as the render
platform throughout (the plan's "rendering is macOS-only" was already
false since Camera Phase 2; the README, the platform module, the test
marker and this report now say Windows everywhere).

**Package F, the prompt surface -- closed.**

- *Multi-camera sentences.* Every view named in a sentence is a camera,
  in the order named, one per preset ("chase and wingman views",
  "cockpit, chase and tower views"); the count, the lens and the moves
  apply to each. Camera ids are the preset names, exactly as the
  page's picker names its views.
- *Move phrases.* A documented deterministic vocabulary: "zoom in" /
  "zoom out" (focal length x2 / /2 over the flight), "push in" /
  "pull back" (an aircraft-relative offset /2 / x2), "orbit" /
  "circle around" (the offset turned a full circle as a 32-segment
  polygon, chord error stated). Each becomes keyframes over the spec's
  duration; the page's clip selector rescales prompt moves to the clip
  (stated keyframe times elsewhere are left alone). Offsets exist only
  on the chase and wingman presets, so a push, pull or orbit asked of
  a tower, ground or cockpit view is reported as ignored, by name.
  "pan"/"tilt" are aim moves no aircraft-aimed preset can make and
  stay in the reported-as-ignored list. The solver gained keyframed
  offsets to carry them, and a keyframe naming a key no solver field
  reads now refuses by name (`camera.moves`) instead of being ignored.
- *The clarifying question.* The regex path asks exactly one question,
  `camera_view`, when a prompt speaks of imagery (photograph, film,
  frames, ...) and names no view; the spec meanwhile carries the
  documented default chase camera so a count or a lens the words did
  state is not lost. The answer round compiles the answer ("from the
  tower" -> a tower camera, source inferred) and asks nothing; an
  answer naming no view keeps the default and says so.
- *The corpus.* `tests/test_camera_prompts.py` scores 26 prompts --
  views, counts, lenses, multi-camera, every move word, the ignored
  cases, the question cases -- and prints the rate; it must be 100%
  and a miss is named with its prompt. (Gate 8's corpus still measures
  the LLM against the regex; this one measures the regex vocabulary
  itself.)

**Package B, rate independence -- closed as far as it can be.** The
lagged presets' filter now integrates the C++ time constants EXACTLY
over each telemetry interval with the goal linear across it
(`lag_step`, first-order hold), so the integrator adds no
rate-dependent error. Measured on the same manoeuvring track as before:
chase 3.294 m -> **0.0003 m**, wingman 3.212 m -> **0.0006 m**, tower
and cockpit 0. What remains is the aircraft track's own interpolation
between samples, which no filter can remove (the two rates sample a
different goal signal), and the complement test now pins it under a
centimetre rather than above half a metre. Keyframed moves were
already bit-identical across rates and still are.

**Package E, the manifest -- closed.** Every frame carries
`intrinsic_matrix` (K) and `projection_matrix` (P = K [R | t], 3x4,
over homogeneous scene points), with the convention stated in
`label_conventions`; the verifier's `projection_matrix` check projects
the aircraft and every landmark through P and through the recorded
parameters and requires agreement to 0.001 px (measured 2.5e-9 px over
1401 projections), failing by frame on a matrix that disagrees. The
schema is published: `docs/schemas/capture_manifest.v5.schema.json`
(JSON Schema 2020-12, `manifest_version` pinned by `const`, a test
pins it to the writer's), validated by `core/capture/schema.py` -- a
dependency-free validator that enforces the keywords the schema uses
and REFUSES a schema using any other, so the file cannot drift past
what is checked -- and run over every manifest by the verifier's
`json_schema` check.

**Tests and guards.** 33 tests across `tests/test_camera_prompts.py`,
`tests/test_capture_schema.py` and the rate tests in
`tests/test_camera_poses.py`; sixteen mutation guards, each shown to
fail its test when removed.

**How to demonstrate.**

    .venv/bin/pytest tests/test_camera_prompts.py tests/test_capture_schema.py -q
    # web app: "photograph a 747 in flight" -> asked which view; answer "tower"
    # web app: "chase and wingman views of the 747 for 20 seconds, zoom in and orbit"
    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo
    .venv/bin/python -m flightsim.verify runs/demo     # json_schema, projection_matrix PASS
