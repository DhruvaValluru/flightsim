# Agent prompt — Camera Phase 1 implementation

Copy everything below the line into the agent session. It is self-contained:
it states the goal, the repository's own conventions, the work packages in
dependency order with concrete file targets, and the acceptance tests.

---

You are implementing **Phase 1 — Camera Control and Capture Geometry** in the
`flightsim` repository. Work on the current default branch conventions of the
repo, commit in small package-sized commits with descriptive messages, and
keep the full test suite green after every commit (`.venv/bin/pytest -q`;
run `./scripts/setup.sh` first if there is no `.venv`).

## Goal

Promote the camera from a fixed render-time preset to a first-class,
attributed, validated element of the scenario specification, and make every
captured frame carry enough geometry to be used as labeled data. A run must
emit a defined number of images rather than a clip, and two runs of the same
specification with different cameras must produce frame sets that align
exactly in time. Everything except actual pixel rendering must run and be
verifiable on Linux/Windows; rendering stays macOS-only behind the existing
`ue.platform` refusal.

Before writing code, read these files completely — they define the
disciplines you must follow, and the codebase enforces them with tests and
mutation guards:

- `core/scenario/fields.py` — `Quantity` (frozen, provenanced) and `Source`
  (`user > inferred > model > derived > default`). Every camera field you add
  is a `Quantity`. No exceptions to the provenance rule.
- `core/scenario/spec.py` — `ScenarioSpec`, `SPEC_VERSION` (currently 5, with
  a changelog comment block above it), `set()` vs `plan()` (a user-stated
  value is NEVER silently moved; planners refuse by name), canonical
  serialization, `digest()`.
- `core/scenario/validate.py` — named `Violation`s (e.g.
  `altitude.terrain_clearance`). Refusals are first-class results, never
  exceptions swallowed or values quietly clamped.
- `core/scenario/card.py` — `write_run_card`: every parameter computed once in
  Python, consumed verbatim by the C++ host, which "derives nothing". Your
  pose track is the next such block.
- `core/scenario/runner.py` — headless `run_spec`, `Recorder` at 0.1 s
  (`SAMPLE_INTERVAL_S` in card.py must match), `_digest_telemetry`.
- `webapp/runs.py` — planners, `PLANNABLE_SOURCES` (load-bearing),
  `WEBAPP_CHASE` offsets, the current `-camera=` selection logic, and
  `_projected_origin` (scene coordinate frames: terrain raster CRS, or the
  spec origin's UTM zone via `core/terrain/glo30.utm_zone_crs`, declared as
  `scene_crs` on the card).
- `webapp/server.py` — `/compile` and `/run`, the pinned planner order, and
  the 409 refusal payload shape.
- `core/nl/compiler.py` and `core/nl/llm_compiler.py` — the deterministic
  vocabulary, `CINEMATIC_WORDS` (currently ignores camera language), the
  generated-from-spec `RESPONSE_SCHEMA`, its strict parse rails, and the
  import-time asserts tying schema to spec fields.
- `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimCameraDirector.cpp`
  and its header — the five presets you will port to Python (LaggedChase,
  GroundObserver, Wingman, Tower, CockpitShoulder), their smoothing time
  constants, and `PresetKeepsHorizonLevel()` (only the cockpit preset
  inherits roll — preserve this and the recorded flag).
- `scripts/mutation_check.sh` — every safeguard you add gets a mutation
  entry that disables it and confirms the test fails.
- `NEXT.md` gotchas — especially gotcha 13: UE-written manifests are
  ASCII-only; UTF-8 provenance goes in Python-written sidecars.
- `docs/BRIEF_CAMERA_PHASE1.md` — the file-level mapping for this phase.

Hard rules, from the repo's own doctrine:

1. `prompt -> spec -> validate -> run`, never `prompt -> run`. Cameras enter
   the spec, appear in the review table with per-field sources, and are
   refused by named constraint when invalid.
2. A user-stated camera field is never silently moved. System choices go
   through `plan()` and become `derived`.
3. Anything a host cannot honour exactly it refuses by name; nothing is
   approximated silently.
4. Determinism: no wall-clock, no frame-rate dependence, no RNG outside the
   seeded subsystems. The pose track and capture schedule are pure functions
   of the telemetry record and the spec.
5. Do not weaken, skip, or delete any existing test or guard. The suite is
   ~429 tests and 88 mutation guards; it must only grow.
6. Rendering changes (package G) must be additive and compile-safe, but you
   cannot run the editor off macOS — keep the Python side demonstrably
   complete without it, and gate every render path behind
   `core/util/platform.ue_available()`.

Implement the packages in this order. Each package = code + tests + mutation
guards + one commit (or a few focused commits).

## Package A — CameraSpec and schema version 6

- New `core/scenario/camera.py`: a `CameraSpec` record whose fields are all
  `Quantity`s, with its own `FIELD_ORDER`-style tuple, `to_dict`/`from_dict`
  (canonical key order, same conventions as `Quantity.to_dict`), and a
  documented default constructor. Fields: `camera_id`; `preset` (one of
  `chase`, `ground`, `wingman`, `tower`, `cockpit`, `explicit`); position as
  either an aircraft-relative offset (behind/right/up metres, the
  `WEBAPP_CHASE` convention) or explicit placement in scene metres or
  geographic lat/lon/alt (a `position_mode` field says which); aim mode and
  target (`aircraft`, `fixed point`, `bearing`); `focal_length_mm` plus
  sensor width/height mm (or a stated horizontal FOV — pick ONE canonical
  representation, store the other in `detail`); output `width_px`/
  `height_px`; `near_m`/`far_m`; and an optional `moves` list of keyframes
  (time-keyed position / aim / focal length). Keyframes are data inside the
  camera record and digest-relevant.
- `core/scenario/spec.py`: add `cameras: List[CameraSpec]` (default empty),
  extend `to_dict`/`from_dict`/`render_table` (each camera renders as its own
  labeled block with per-field sources), extend `set()`/`plan()` so camera
  fields are addressable (e.g. dotted names `cameras[0].focal_length_mm`)
  with the same stated-value-never-moves refusal. Bump `SPEC_VERSION` to 6
  and add the changelog comment line explaining why, following the existing
  comment block's style. Serialize `cameras` as an always-present list so
  the canonical form has one spelling of "no cameras".
- Defaults: an empty camera list must behave EXACTLY like today's build.
  Provide `default_cameras(spec)` returning the documented default (the
  chase preset with the `WEBAPP_CHASE` per-airframe offsets, current fps and
  resolution), and use it wherever the render flow currently hardcodes the
  choice. Add a test asserting the commandlet argument list built for a
  camera-less spec is unchanged.
- Update `webapp/server.py _spec_payload` and `webapp/static/index.html` so
  cameras appear in the review table as labeled blocks and remain editable
  like every other field.
- Tests (`tests/test_camera_spec.py` + updates to
  `tests/test_scenario_spec.py`): YAML round-trip preserves digest; two specs
  differing only in cameras hash differently; a `spec_version: 5` document
  refuses with the named version error, not a partial load; camera field
  edit → source `user`; `plan()` on a user-stated camera field refuses.

## Package B — deterministic pose solver

- New package `core/capture/` with `poses.py`: a pure function
  `solve_pose_track(columns, camera, scene_frame)` mapping recorded telemetry
  (the `Recorder`'s 0.1 s columns: `t`, `lat_deg`, `lon_deg`, `altitude_m`,
  `roll_deg`, `pitch_deg`, `heading_deg`, …) and a `CameraSpec` to a
  per-sample pose track: world position (scene metres), orientation
  (quaternion AND Euler), and the full intrinsic set (focal length, sensor,
  principal point, resolution, near/far). No engine, no wall clock, no RNG.
- Port the five presets from `FlightSimCameraDirector.cpp` faithfully:
  heading-only frames for chase/wingman (never inherit roll), world-anchored
  ground/tower with aim smoothing, body-fixed cockpit (full rotation, roll
  inherited BY DECLARATION). Implement the exponential smoothing as the
  discrete filter on the fixed telemetry clock with the C++ time constants,
  and record per camera a `horizon_stable` flag mirroring
  `PresetKeepsHorizonLevel()`.
- Scene frames: reuse the `_projected_origin` pattern — terrain scenes
  project through the raster's `georeference.crs`, flat scenes through
  `utm_zone_crs`, via `pyproj.Transformer`. Explicit geographic placement
  resolves through the same transformer.
- Keyframed moves: deterministic piecewise interpolation (linear for
  position/focal, slerp for orientation) keyed on simulation time; no
  dependence on sample rate beyond sampling the continuous solution.
- Tests (`tests/test_camera_poses.py`): bit-identical across repeated
  invocations (compare `repr` of arrays, the `_digest_telemetry`
  convention); resampling the same keyframes at a different telemetry rate
  agrees at shared sample times; only cockpit inherits roll (drive a rolling
  telemetry track and assert camera roll is 0 for the other four and equal
  to aircraft roll for cockpit); a preset ported wrong in the heading-only
  frame must fail these.

## Package C — capture scheduling

- `core/capture/schedule.py`: triggers evaluated over the telemetry record
  ONLY (never render timing), returning the exact list of capture times
  (sample-aligned):
  - fixed interval, expressed as a period or as an exact image count over
    the run window (count → deterministic times, endpoints included/excluded
    documented);
  - waypoint triggers: every N metres along the flown ground track, or
    proximity to a stated coordinate;
  - event triggers over recorded channels (e.g. `roll_deg`, `n_z`, `agl_m`
    crossing a threshold) with a documented refractory period so one event
    is one capture.
- The scheduler guarantees the emitted count exactly matches a requested
  count, or refuses before running with a named `camera.schedule` reason
  (count unreachable at the run duration/rate, trigger outside the window,
  negative count).
- Tests (`tests/test_camera_schedule.py`): count exactness across all three
  trigger kinds; schedule is identical with rendering absent (it only ever
  sees telemetry); refractory period collapses bursts; out-of-window and
  unreachable requests refuse by name.

## Package D — validation and refusal

- `core/capture/validate.py` producing the existing `Violation` type:
  - `camera.intrinsics` — non-physical lens/sensor values, unsupported
    resolutions, near/far ordering. Scene-free: call it from
    `core/scenario/validate.py:validate()` so it appears everywhere.
  - `camera.schedule` — package C's refusals, also raised at validation.
  - `camera.terrain_clearance` — the SOLVED pose track checked against the
    scene raster (`Heightfield.elevation_at`) along the WHOLE track with a
    minimum clearance, not the first frame only.
  - `camera.scene_bounds` — poses outside `Heightfield.bounds_m` /
    `contains` where terrain and imagery do not exist.
  - `camera.hazard_intersection` — poses inside a modeled hazard volume;
    reuse `core/environment/tornado.R_CORE_M` and the card's vortex
    placement for tornado runs.
- Scene-coupled checks (`terrain_clearance`, `scene_bounds`,
  `hazard_intersection`) follow the `plan_terrain_flight` pattern: computed
  in the run flow where the scene raster is known (`webapp/server.py /run`
  and the package-I CLI), returned as violation dicts merged into the
  verdict, so they surface in the web UI exactly like `terrain.clearance`
  does today.
- A user-stated camera field is never silently moved to pass validation —
  refusal by name is the only path. A system-chosen (default/model/derived)
  camera placement MAY be planned via `spec.plan` with a recorded reason,
  matching the altitude planners.
- Tests (`tests/test_camera_validate.py`): one test per named constraint
  that TRIPS it and asserts the refusal (e.g. a camera placed inside a
  mountain via a small synthetic `Heightfield`; a pose inside the tornado
  core; a 0 mm focal length; an unreachable count), plus one asserting a
  stated camera field never moves. Add a `scripts/mutation_check.sh` entry
  per constraint disabling the check and confirming its test fails.

## Package E — capture manifest

- `core/capture/manifest.py` writing `capture_manifest.json` for every run,
  on every platform, whether or not pixels were produced:
  - per frame: index, simulation time, camera id, image filename (relative,
    per-camera subdirectory), camera world position, orientation as
    quaternion AND Euler, full intrinsics including principal point and
    resolution, the projection matrix (or the exact parameters it is
    reconstructible from — document which), aircraft position and attitude
    at that instant, and the geographic reference frame (CRS string) all
    positions are expressed in;
  - per run: spec digest, telemetry digest (`output_digest`), random seed,
    scene key, terrain raster digest (SHA-256 of the `.r16`), and the
    software version (git revision);
  - a `manifest_version` field and a documented schema (docstring or
    `docs/`), so consumers validate before parsing.
- Do not touch existing fields of the UE `render.json` — package G extends it
  additively so current gate scripts keep passing.
- Tests (`tests/test_camera_manifest.py`): manifest written headlessly with
  no engine present; every per-frame field present and finite; digests match
  the run's own; schema version present.

## Package F — prompt surface

- `core/nl/compiler.py`: add a deterministic camera vocabulary — named views
  ("chase", "from the tower", "ground observer", "wingman view", "cockpit"),
  image counts ("50 images/frames/stills"), simple lens words with
  documented mm mappings ("wide angle", "telephoto", "35 mm lens"), and
  simple move phrases only if they map to keyframes. Remove the words you
  now map from `CINEMATIC_WORDS`; keep genuinely unexpressible shot language
  reported in `notes` as today.
- `core/nl/llm_compiler.py`: extend `RESPONSE_SCHEMA` with a bounded repeated
  `cameras` block (each camera field provenanced value/source/from like
  `_field_schema`), extend `_parse_payload` rails (unknown camera fields
  refuse; model-sourced values need quoted phrases; bounded list length) and
  `_overlay` into `CameraSpec` quantities. Keep the
  generated-from-the-spec asserts: add one tying the camera schema to
  `CameraSpec`'s own field list.
- Clarifying question: when the prompt implies imagery ("photograph",
  "capture", "images of") but names no viewpoint, the model may ask one
  camera-intent question, under the existing one-round/three-question caps.
- Extend the gate 8 corpus (`experiments/gate8_compiler.py`) with camera
  prompts so extraction is measured, not assumed.
- Tests: `tests/test_nl_compiler.py` and `tests/test_llm_compiler.py`
  additions — vocabulary mappings with provenance, schema round-trip through
  the mock client, rails refusing malformed camera entries.

## Package G — engine consumption (macOS only; additive; do last)

- `core/scenario/card.py write_run_card`: new optional `cameras` argument —
  a list of camera dicts each carrying its spec fields AND its solved pose
  track (per-sample position, quaternion, intrinsics at the card's
  `SAMPLE_INTERVAL_S`). Computed in Python, consumed verbatim.
- `FlightSimCameraDirector`: a consume-poses mode that interpolates the
  card's track per frame instead of computing presets, refusing by name when
  the track does not cover the run duration. Keep the existing preset code
  for the interactive host.
- `FlightSimRenderCommandlet`: one render pass per camera from the same
  card, frames into per-camera directories; emit the same per-frame manifest
  fields as package E additively into `render.json` (ASCII only — gotcha
  13); compare applied vs solved pose per frame and FAIL LOUDLY beyond a
  stated tolerance; reuse the existing world-to-pixel projection to verify
  the aircraft position projects into the frame.
- `webapp/runs.py`: replace the hardcoded `-camera=` selection with the
  spec's cameras (default cameras when none stated — behaviour identical);
  the tornado core chase→wingman rule becomes a documented camera planner
  (`plan()`-recorded, stated cameras never moved).
- You cannot run the editor off-mac: keep C++ changes compiling logically
  (mirror the existing code style; `scripts/check_bridge_api.sh` exists for
  API surface checks) and leave a clearly marked verification step for a
  macOS session in the phase report.

## Package H — verification (woven through, plus the runner)

- `core/capture/verify.py` + `flightsim/verify.py` CLI (see package I): runs
  alignment, recovery, and consistency checks over a run directory and
  prints a pass/fail summary:
  1. **Temporal alignment** — same spec run twice with different camera sets:
     identical spec digest (camera fields excluded from a defined
     "simulation-identity" comparison — the telemetry digests must match),
     identical frame counts, per-frame sim times equal to float tolerance.
  2. **Geometry recovery** — an INDEPENDENT reprojection implemented inside
     the test/verifier (do not import the producer's projection code):
     known world points through the recorded pose+intrinsics land within a
     stated pixel tolerance of the producer's own result.
  3. **Cross-view consistency** — a world point visible from two cameras at
     the same instant triangulates back within tolerance.
  4. Count exactness and refusal coverage as per packages C/D.
- The exit criterion is 1–3 passing. Add `scripts/mutation_check.sh` entries:
  disable each new safeguard in turn and confirm the matching test fails.
- Engine parity (macOS only): rendered frames agree with the solved manifest
  within tolerance by projecting the aircraft position into the frame.

## Package I — demonstration, CLI, documentation

- New top-level `flightsim/` package (the instructor commands name it; it
  does not exist yet): `flightsim/capture.py` and `flightsim/verify.py` with
  `python -m` entry points wrapping `core.capture` + `core.scenario`:
  - `.venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo`
    → validates, runs headlessly, solves poses, schedules captures, writes
    `capture_manifest.json` + a geometry preview image set; on macOS it
    additionally renders real frames; off-mac rendering refuses by NAME
    (`ue.platform`) while everything else succeeds.
  - `.venv/bin/python -m flightsim.verify runs/demo` → package H's summary.
- `core/capture/preview.py`: a geometry preview renderer with numpy +
  Pillow ONLY (matplotlib is not a dependency): terrain raster contours or
  shaded relief and the aircraft track projected through the recorded camera
  matrix, one image per scheduled frame, drawn without the engine.
- Commit two or three example specs under `examples/`: a multi-camera
  fixed-interval capture, a waypoint capture over a real bake, and a refusal
  case with a camera placed inside a mountain (its expected refusal named in
  a comment).
- A short report `docs/CAMERA_PHASE1_REPORT.md`: what was implemented, what
  was not, how to run each demonstration, expected output on and off macOS,
  and known limitations (the macOS rendering boundary; keyframed moves only,
  no simulated camera platforms).
- Update `README.md` with the capture/verify commands.

## Out of scope — do not build

Segmentation masks/bounding boxes, domain randomization, batch execution,
ground/vegetation/weather visual improvements, the agent controller, porting
rendering off macOS, physically simulated camera platforms.

## Definition of done

- Full suite green on Linux (`.venv/bin/pytest -q`), including all new
  `tests/test_camera_*.py`; `scripts/mutation_check.sh` green including the
  new guards.
- `python -m flightsim.capture` + `python -m flightsim.verify` succeed
  off-mac end to end (manifest + preview + passing verification; rendering
  refused by name).
- A camera-less spec produces byte-identical behaviour to the current build,
  proven by test.
- Version-5 specs refuse by name.
- The phase report exists and is accurate about what remains (macOS parity
  verification if you could not run the editor).
