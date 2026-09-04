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
  aircraft state at that instant (with its speed, `speed_mps`, from the
  recorded true airspeed); per run the spec digest, the
  camera-free `simulation_digest`, the telemetry `output_digest`, the
  seed, the spec's fixed-step `rate_hz` and `step_s` (the grid every
  capture instant lies on -- a schedule off it is refused
  `camera.schedule` by name), the terrain raster SHA-256, the scene-frame
  CRS and the git revision.
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

Expected without the engine (measured 2026-09-03 on Linux, exit 0;
the JSBSim banner omitted; the default render choice resolves to
`none` there, so `--render none` is implied):

```
spec cef57d752362381d valid; running headlessly...
scheduled 48 frames across 2 camera(s)
  manifest: runs/demo/capture_manifest.json
  previews: 48 geometry preview(s) at 1280x720, 0.049 s/frame under runs/demo/previews (previews are not frames)
  contact sheets: 2 (contact_sheets/<camera_id>.png, one per camera)
  [PASS] manifest_version: manifest_version 1, spec cef57d752362381d
  [PASS] fields_finite: 48 frame records checked
  [PASS] geometry_recovery: 48 frames; quaternion-vs-euler reprojection gap 0.0000 px (tol 0.5); 0 aircraft behind camera; 0 aimed frames without the aircraft in frame
  [PASS] cross_view_consistency: 24 two-view instants; worst triangulation error 0.0000 m (tol 0.5)
  [PASS] count_exactness: 2 camera(s), every declared count met exactly
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification PASSED (5/5 checks; 1 awaiting engine frames: engine_parity)
engine absent: no engine on this OS: the render half needs macOS, or Windows with Unreal Engine 5.5 and the FlightSimBridge built; frames not rendered (--render frames where the engine exists)
done: manifest, 48 previews and verification for 48 scheduled frames under runs/demo (no pixels)
```

Every mode runs that verifier on the manifest it just wrote and prints
the table BEFORE its final line (clip mode too, before its engine pass;
frames mode prints the complete table after its passes, when engine
parity has frames to grade), writes it as `verify.json` beside the
manifest (the same JSON the webapp serves, so `flightsim.verify`'s
output and the run's own record agree without re-running), records the
render choice in `run.json` (`render`: the word, the page's label, and
the engine's availability and reason on this machine -- the CLI's copy
of the webapp's `provenance.json` `render`), and a manifest that fails
its own verification fails the run by name (`capture.verification`,
exit 2). The headless tree is `capture_manifest.json`, `telemetry.json`,
`scenario.yaml`, `run.json`, `verify.json`, `previews/<camera_id>/
preview_NNNNN.png` (full resolution) and `contact_sheets/<camera_id>.png`
(see "Geometry preview" below; `run.json` `previews` records the scale,
the resolution and the measured seconds per frame).
The word REFUSED is reserved for exit 2: a headless run on a machine
without the engine is DONE, and states the engine's absence by reason.
`--render frames` there refuses BY NAME (`ue.platform`, "rendered
frames and clips require ...") with the machine's reason -- the
designed outcome, not a failure. With the engine built the default is
`--render frames` and the same command renders 24 PNGs per camera and
grades them (see "Engine verification (Windows)" below).

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

## Geometry preview (package I, done properly 2026-09-04)

`core/capture/preview.py` draws one PNG per scheduled frame with numpy
and Pillow only (matplotlib is not a dependency), every element
projected through the frame's OWN recorded pose and intrinsics by the
verifier's independent `project_point`, so the picture is an eyeball
check on the manifest: a wrong record would draw in the wrong place.
What a reader sees, and the field each element comes from:

| element | drawn as | source |
|---|---|---|
| terrain (terrain scenes) | a 48 x 48 wireframe of the raster, each sample joined to its row and column neighbour, clipped at the near plane and to the image, shaded by camera-space depth: 240 at the frame's subject range (camera to aircraft) falling on a log scale to 32 at `far_m` | the heightfield, `near_m`, `far_m`, the aircraft state |
| ground grid (flat scenes) | a fine lattice (step = the nice number at or above height/4) and a coarse one (10x that step) on the plane at the spec's terrain elevation, centred beneath the camera, extent = min(`far_m`, fy x height / 2) so it reaches the horizon or the far plane; distance rings at 500 m, 1, 2, 5, 10, 20 km labelled; a north arrow one step long where the boresight meets the plane | `position_*_m`, `fy_px`, `far_m`, the spec's terrain elevation |
| horizon | the level directions at infinity projected: `v = cy + fy tan(pitch)` for a level-rolled camera (a camera pitched down sees it ABOVE centre), tilted by roll | `quaternion_wxyz`, intrinsics |
| aircraft | a three-axis body: nose-tail along the recorded heading and pitch, wing tips at +/- span/2 with the recorded roll, a fin up from the centre; the length x span x height box; a heading tick beyond the nose; the flown track (past solid, future dim) | `aircraft.*` per frame; `aircraft_metrics` (below) |
| camera | a boresight cross at `principal_point_px` with the FOV `2 atan(sensor / 2 focal)` printed at the edges | `principal_point_px`, focal, sensor |
| header | camera id, frame index / capture count, t, position, look yaw/pitch/roll, focal and fx, resolution, FOV; the aircraft's position, attitude, the aircraft-to-camera bearing and range; the body's span, length and height with their sources | the record; the camera block |

**The airframe metrics are read once from the FDM, never a constant**:
`core.scenario.runner.aircraft_metrics(fdm)` reads `metrics/bw-ft`
(span; the same property the span-station contact check uses),
`metrics/lh-ft` + `metrics/cbarw-ft` (the wing-to-tail arm plus one
mean chord: the FDM's longitudinal extent -- JSBSim states no
nose-to-tail length, and the source string says so) and
`sqrt(metrics/Sv-sqft)` (the vertical tail area's square side: the
FDM's only vertical extent). The run manifest and the capture manifest
carry the block as `aircraft_metrics` (B747: span 64.47 m, length
40.82 m, height 8.78 m). A manifest without it (a synthetic one) gets
a fixed cross and a header line "aircraft_metrics absent: body
unscaled" -- never a silent guess.

**Resolution.** Full output resolution by default (the record's
`width_px` x `height_px`); `--preview-scale N` on the CLI and the
page's "preview scale 1/N" field draw at 1/N, the header and the CLI
line say so only when N is not 1, and a value that is not a positive
integer is refused by name (`preview.scale`) before any flight.

**Measured render time** (this machine, Linux, 2026-09-04, the 48
frames of `examples/cameras_multi.yaml`, flat scene): 0.049 s/frame at
1280x720 including the lattice, rings, track, body and header; 0.029
s/frame at 1/2 scale; 0.064 s/frame including the contact sheets. The
budget is 0.5 s/frame (`RENDER_BUDGET_S_PER_FRAME`), graded by
`tests/test_camera_preview.py::test_full_resolution_render_time_is_under_budget`
and printed by every run ("0.049 s/frame"); `run.json` `previews`
records it.

**Overlays** (`overlays/<camera_id>/NNNN.png`): after an engine pass,
`render_overlays` draws the same geometry as a translucent layer over
every rendered PNG that exists (named by the same index, the frame's
own size): the reprojected aircraft box, the ground and the horizon on
the engine's pixels, so the verification is visible to the eye. The
CLI prints "overlays: 48 reprojected-geometry overlay(s) ... (0.0xx
s/frame)" and records `overlays {count, s_per_frame}` in `run.json`;
the page lists `capture/overlays/<camera_id>` with the note
"reprojected geometry over the rendered frame". Exercised here only
against the honest engine STUB (a blob at the labelled pixel);
"awaiting Windows verification" on real pixels, step 5c below.

**Contact sheets** (`contact_sheets/<camera_id>.png`, beside
`previews/`, never inside it -- `previews/` holds exactly one PNG per
drawn frame): every preview of the camera as a 320-px-wide thumbnail
with its index and time, a title row with camera id, preset, schedule
basis and "N of M frames". Listed by the CLI and shown whole on the
page above the per-frame gallery.

**Reference image**: `docs/images/preview_chase0_frame5.png` is frame 5
of `chase0` from the command above (t=2.683 s, camera at N +268.4, alt
3060 m, pitch -4.8 deg): the horizon at row 256 (= 360 + 1244 tan(-4.8
deg)), the 747's 64.5 m span drawn 455 px wide at 176 m range
(1244 x 64.5 / 176 = 456), the box around it, the boresight cross, the
10 km and 20 km rings and the coarse lattice dim in the distance.

**Tests** (`tests/test_camera_preview.py`, 20 tests on synthetic
records with known poses): the level camera's horizon row equals cy
within 1 px and a ground point ahead lands below it; pitch -10 deg
moves it by fy tan(pitch); the body centre equals `project_point` of
the aircraft within 1 px; the wing-tip separation equals fx x span /
range within 1 px and halves at twice the range; roll and heading move
the tips and nose as recorded; a segment behind the camera is not
drawn, even when its mirrored projection would land in frame; the
default size is the record's; the header carries the position, look
and focal strings; the overlay is the frame's size with the body at
the reprojected pixel; one contact sheet per camera with one thumbnail
per frame; the render time is under budget. 15 mutation guards
(`scripts/mutation_check.sh`, "the geometry preview") disable each
safeguard in turn and were verified to fail their tests.

## The run emits frames, not a clip (finished 2026-09-03)

The first Windows run of this phase produced a clip plus schematic
previews: the web flow never invoked the engine's consume-poses pass.
Now it does, and the choice is explicit:

* **The render choice** -- the run form's `<select id="render">` with
  exactly *Render frames and clip* / *Clip only* / *Headless*, and the
  CLI's `--render frames|clip|none` with the same words. The default is
  the richest option the machine supports (`/status` reports
  `render_default` and `render_unavailable_reason`; the page disables
  the engine options WITH the reason, e.g. "no engine on this machine:
  set UE_ROOT ..." or "FlightSimBridge not built: run
  scripts\ue_preflight.ps1 then scripts\build_ue.ps1" -- and macOS is
  gated on the SAME two facts, the editor at UE_ROOT and a built
  `.dylib`, with `scripts/ue_preflight.sh then scripts/build_ue.sh`
  named, so a mac without the engine is told so before a run, never
  offered *Render frames and clip* as a default it cannot honour;
  `ue_available()` IS `ue_unavailable_reason() is None`). There is no
  hidden default: the control ships DISABLED with *Headless* selected
  and is enabled only once `/status` has answered with
  `render_default` -- the one rule the CLI uses too,
  `core.capture.render_pass.render_choice_default()` -- so a slow or
  unreachable server never shows an engine option as the default (the
  page says "render choice unavailable: server unreachable"); the JS
  that does this (`applyRenderChoices`) is driven verbatim under node by
  `tests/test_webapp_capture.py` against the real `/status` payload, and
  its markup and lines are pinned at the source. A `POST /run` that
  OMITS the field (an API client) resolves through the same one rule,
  `render_choice_default()`, and the reply echoes the resolved word --
  headless on a machine without the engine, frames where it exists;
  there is no second spelling of the default on the server and the
  page prints the server's word with no fallback of its own (pinned
  under both gate states by `tests/test_webapp_capture.py`). An engine
  choice on a machine without the engine is refused `ue.platform` by
  name with that reason -- never degraded to headless. The choice is recorded as
  `render` in `provenance.json` and the final status line names what
  came out: "48 frames across 2 camera(s) rendered (48 scheduled, 48
  verified by engine parity) + clip (by-product of 'chase0')", "clip
  only: 48 frames scheduled, 0 rendered (...)", "headless: manifest +
  48 previews for 48 scheduled frames, no pixels (no engine pass)".
* **The frames flow** (`webapp/runs.py` `_frames_passes`,
  `flightsim/capture.py --render frames`): the capture half runs FIRST
  so `card.json` carries `cameras=[...]` -- solved per-sample pose
  tracks, per-sample focal lengths, intrinsics and `capture_times_s`,
  through the ONE builder `core.capture.poses.camera_card_blocks` -- for
  the whole flight the schedule spans (not the clip's 22 s cap). The
  commandlet then runs once per camera with `-camera-index=N` and
  `-frames=<run>/capture/frames/<camera_id>` (no `-camera=`/`-chase=`
  words), through the ONE argument builder
  `core.capture.render_pass.render_command`. Every pass is graded
  against the schedule it was handed (`check_render_pass`: render.json
  present, the engine's own `frames_captured == frames_scheduled ==`
  the schedule, every `NNNN.png` on disk); anything short fails the run
  as `[render.frames] camera '<id>': ...` and the previews are never
  presented as frames. A pass stops after its last scheduled instant
  (the schedule defines the run the frames need; telemetry and the
  closure pair cover the flight) and says how far it stepped
  (`steps_taken`, `stepped_s` in render.json; "camera 'chase0': 24 of
  24 scheduled frames rendered (engine stepped 11.992 s in 1439
  steps)"), recorded per camera as `render_passes` in provenance.json
  (the CLI: run.json). The clip is a by-product of camera 0 -- its
  frames at their scheduled instants through ffmpeg's concat demuxer,
  a black lead-in PNG (`frames/clip_lead.png`, the frames' own size)
  listed first for the time to the first instant, so clip time equals
  simulation time; the argv is spelled once (`clip_command`) and pinned
  by test, the expected length is stated before encoding
  (`scheduled_clip_seconds`: first instant + span + 1 s hold, 12.992 s
  for the example) and recorded with `clip_encoded`, whether or not the
  clip came out; no telemetry panel (the panel is fps-locked).
* **The counts** -- every summary carries `scheduled` / `rendered` /
  `verified` per camera: rendered is PNGs the verifier counted on disk,
  verified is frames engine parity graded. A headless or clip-only run
  says "N scheduled, 0 rendered", and "previews are not frames".
* **Engine parity** (`core/capture/verify.py` `verify_engine_parity`,
  check 5): per camera, `frames/<camera_id>/render.json` matched to the
  manifest by `frame_index`; applied position within 0.10 m, applied
  yaw/pitch/roll within 0.1 deg, `t_applied_s` EQUAL to `t_s` (tolerance
  1e-6 s, representation slack: every instant lies on the MANIFEST's
  `rate_hz` grid and the commandlet captures on the step whose run clock
  equals it -- a capture one step late is a different FDM state and
  fails by name; render.json's `step_s` is a fact checked against
  1/rate_hz, "the engine stepped 10 s against the spec's 120 Hz", never
  the tolerance, so the file being judged cannot declare its own), the
  PNG named by the index at the manifest's width x height, the engine's
  counts equal to the schedule, and the aircraft reprojected through the
  APPLIED pose within 3 px of the manifest's own projection (and inside
  aimed frames). Then the aircraft the engine actually DREW
  (`aircraft_applied_*`: its own FDM's state at the capture) is JUDGED,
  not reported, against ONE budget computed per run from the manifest,
  never a constant for some other aircraft:
  `budget = (1 + 0.5) steps x speed_mps / rate_hz` -- the measured host
  phase (docs/VALIDITY.md: the two hosts' calm flights agree to 3.6e-4 m
  in altitude and differ in position by a CONSTANT phase of EXACTLY ONE
  fixed step, 1.24 m at 250 kt, the headless host's extra step during
  engine start) plus half a step of margin (the phase was measured at
  one envelope point; half a step covers a trim start that differs by
  less than a step WITHOUT admitting a second whole step, which is the
  clock offset the time clause refuses -- so the two clauses cannot
  contradict each other, and a one-step-late clock fails cleanly by
  name, never "within contract" on one line and over budget on the
  next). The arithmetic is printed: on `cameras_multi` (322.74 kt TAS =
  166.03 m/s from the recorded `tas_kt`, 120 Hz) "budget 2.08 m = 1.5
  steps x 1.384 m/step at 166.0 m/s"; a slow c172 run earns a smaller
  budget, a fast one a larger, each its own. In pixels the budget is
  graded by depth, `3 px + fx * budget / depth`: measured on
  `cameras_multi` the chase frames sit 110.7-177.1 m from the aircraft
  (26.3-17.6 px), the tower frames 3074-3262 m (3.8 px) -- and inside
  an aimed frame; a record without the drawn aircraft FAILS the frame.
  The expected drawn-aircraft distance on the Windows run is ONE number:
  about 1.38 m (the measured one-step phase at this TAS), against the
  2.08 m budget; a diverged FDM fails by name with the number. A
  spec whose air CANNOT agree across hosts -- a turbulence word, or the
  lee rotor a terrain scene attaches -- is refused `render.host_parity`
  by name before any editor time (POST /run 409, the flow, and the CLI),
  because same-seed turbulence host parity was measured and REFUSED
  (docs/VALIDITY.md); *Clip only* keeps its visual-only label there.
  **The pixels are judged, not only the engine's numbers about itself**
  (round 3): (1) the commandlet projects the aircraft actor and its
  bounds' corners through the capture's own transform and field of view
  -- `ProjectToPixel`, the landmarks' call -- and writes `aircraft_px`,
  `aircraft_py`, `aircraft_visible`, `aircraft_bbox_px` per frame; the
  verifier requires them, requires `aircraft_visible` wherever the label
  lies in frame, grades the engine-measured pixel against the manifest's
  labelled pixel within the graded budget above ("the engine measured
  the aircraft at (680.4, 355.9) px, 40.0 px from the labelled pixel
  (620.4, 355.9) (tol 5.5 px)") and against the verifier's own
  projection of the drawn aircraft through the applied pose within 3 px
  -- the capture FOV is `2 atan(sensor / 2 focal)`, so a tan-based and an
  fx-based projection describe one lens or the frame fails ("disagrees
  with the manifest's projection model by 10.00 px (tol 3.0); the two do
  not describe one lens"); (2) a pixel-content clause reads the PNG: the
  luminance window around the labelled pixel (half size the larger of 16
  px and the frame's graded budget, widened to the engine's screen box)
  must differ from a same-size window at the frame corner farthest from
  the label by at least 8 of 255 in mean or in spread
  (`ENGINE_LABEL_CONTRAST_MIN`; `label_window_contrast` in
  `core/capture/verify.py`), so a mesh that never loaded -- the measured
  failure the commandlet documents, the 747 body absent from every frame
  while captures "succeeded" -- fails by frame with both windows'
  numbers: "nothing is drawn at the labelled pixel of
  frames/tower0/0007.png: label window [604:638, 339:373] mean 30.0 std
  0.0 against background mean 30.0 std 0.0, contrast 0.0 (min 8)". Pinned
  by `tests/test_camera_verify.py`: a flat frame fails, a blob 40 px from
  the label fails, the blob at the label passes with the contrast stated
  ("lowest label window contrast 37.8 against background 30.0 (min 8)"
  on the synthetic frames); the engine stubs in all three test files
  DRAW the blob where the manifest says and record their own pixel, so
  no stub can pass on a flat PNG. The 8-of-255 threshold and the window
  rule are stated, not measured on rendered pixels: the Windows run
  below measures the real contrast (aircraft against sky and against
  ground) and this number is revisited from it.
  With no render.json anywhere the check is **AWAITING** --
  `[AWAITING] engine_parity: awaiting engine frames ...` -- neither
  passed nor failed and never counted among the passed; some cameras
  rendered and others not is a FAIL. `verify.json` carries `status`,
  `data` (per-camera counts and worst gaps), `passed`, `ran`,
  `awaiting`.
* **Frames are named by their manifest index**: `frames/<camera_id>/
  0000.png ...` in the manifest's `file` field and on disk.

### What the commandlet's consume-poses pass now does (C++, UNCOMPILED here)

`FlightSimRenderCommandlet.cpp` + `FlightSimCameraDirector.{h,cpp}`,
additive; preset cards without a `cameras` block fly byte-identically.
In the `-camera-index=N` pass it:

1. reads the camera block's `poses` (with `focal_length_mm` per sample
   -- refused if absent), `capture_times_s` (refused if absent or not
   strictly increasing: a frame count from the render fps is the
   failure this pass exists to end), and `width_px` / `height_px` /
   `sensor_width_mm` / `sensor_height_mm` (refused if absent; a sensor
   aspect that differs from the pixel aspect is refused: square pixels
   only);
2. refuses BEFORE any editor time when the schedule lies outside the
   solved track's span, and again when the last scheduled instant
   exceeds the run's duration;
3. sets the render target to the block's pixel size (overriding
   `-width`/`-height`, logged) and the capture's horizontal field of
   view to `2 atan(sensor_width / 2 focal)` -- per frame, from the
   interpolated focal -- so the manifest's `fx`/`fy` and the pixels
   describe one lens;
4. captures ONLY at the scheduled instants, on the fixed step whose RUN
   clock equals the instant. The rule in one sentence: every instant is
   `k / rate_hz` (the Python side refuses any other by name before
   editor time, `camera.schedule ... off the 120 Hz fixed-step grid`),
   the commandlet reads the FDM clock once before its first step
   (`clock_origin_s`, logged and recorded) and subtracts it from every
   reading, so the k-th step meets the instant exactly and a trim
   sequence or engine start that advanced the clock cannot shift the
   schedule; a step that passes an instant without meeting it fails
   the pass by name ("is not on the fixed-step grid") -- nothing is
   rounded to a nearest step, which is why "nearest" and "at or after"
   never differ here. `-fps` plays no part;
5. applies the pose AT THE SCHEDULED INSTANT (`ApplyPoseAtTime(t_sched)`,
   the instant the manifest's solved pose was computed at), never at
   the engine clock's reading, so the pose contract is exact by
   construction; the run clock is recorded beside it as `t_applied_s`
   (the raw FDM clock as `t_clock_s`) and the instant the pose was
   taken at as `t_pose_s` (the verifier fails a frame whose `t_pose_s`
   or `t_applied_s` is not the manifest's `t_s`, to 1e-6 s);
6. names each PNG `%04d.png` by its manifest index and writes per
   frame `frame_index`, `t_scheduled_s`, `t_applied_s`, `t_pose_s`, the
   applied pose (`camera_applied_*`), the SOLVED pose it was compared to
   (`camera_solved_*`), `camera_applied_focal_length_mm`,
   `camera_applied_fov_deg`, the aircraft this host drew
   (`aircraft_applied_*`), all in the card's local frame, and its OWN
   projection of that aircraft through the capture (`aircraft_px`,
   `aircraft_py`, `aircraft_visible`, `aircraft_bbox_px` = the bounds'
   eight corners' screen box when all lie in front of the camera,
   `aircraft_bbox_corners_in_front`); the root
   carries `frames_scheduled`, `frames_captured`, `step_s`,
   `clock_origin_s`, `steps_taken`, `stepped_s`, `capture_fov_deg`, the
   sensor size;
7. `ApplyPoseAtTime` FAILS the pass (never warns) when the applied
   position differs from the solved one by more than 10 cm
   (`PoseParityPositionCm`) OR the applied orientation by more than
   0.1 deg (`PoseParityAngleDegrees`);
8. stops stepping after the last scheduled capture ("consume-poses:
   stopped after the last scheduled instant at t=... s (N of M
   steps)") -- the schedule is the run the frames need; the steps
   actually integrated are what `steps_taken` / `stepped_s` report;
9. fails after the loop when `captured != scheduled`.

## Engine verification (Windows)

**Status: NOT YET RUN.** Nothing in this section is verified until the
log below has been pasted back from the Windows machine and read.
This environment has no engine; the C++ above is compile-safe by
inspection only (`scripts/check_bridge_api.sh` and the static shadowed-
locals test in `tests/test_platform.py` are the only checks it has had).

### 1. Build the plugin

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ue_preflight.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_ue.ps1
```

Preflight must end `Preflight OK`; the build must produce
`ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.dll`
(the file `core.util.platform.ue_available()` gates on). The first
compile of the new code is where an ordinary C++ mistake would surface:
paste the build log back if it fails.

### 2. The whole thing in one command

```
.venv\Scripts\python -m flightsim.capture examples\cameras_multi.yaml --out runs\demo --render frames
```

Expected output (the numbers come from the headless run of this
example on 2026-09-03: 115 telemetry samples, 24 captures per camera
from t=0.008 s to t=11.992 s, 1440 steps of 0.008333 s):

```
spec cef57d752362381d valid; running headlessly...
  card:     runs\demo\card.json (consume-poses; one commandlet pass per camera via -camera-index=N)
scheduled 48 frames across 2 camera(s)
  manifest: runs\demo\capture_manifest.json
  previews: 48 geometry preview(s) at 1280x720, 0.0xx s/frame under runs\demo\previews (previews are not frames)
  contact sheets: 2 (contact_sheets/<camera_id>.png, one per camera)
engine pass 1 of 2: camera 'chase0', 24 frames scheduled over the 12 s run (-camera-index=0)
  camera 'chase0': 24 of 24 scheduled frames rendered under runs\demo\frames\chase0 (engine stepped 11.992 s in 1439 steps)
engine pass 2 of 2: camera 'tower0', 24 frames scheduled over the 12 s run (-camera-index=1)
  camera 'tower0': 24 of 24 scheduled frames rendered under runs\demo\frames\tower0 (engine stepped 11.992 s in 1439 steps)
  overlays: 48 reprojected-geometry overlay(s) over the rendered frames under runs\demo\overlays (0.0xx s/frame; the aircraft box, wireframe and horizon the manifest predicts, drawn on the engine's pixels)
  clip:     runs\demo\clip.mp4 (by-product of camera 'chase0', 24 frames at their scheduled instants; 12.992 s = black to t=0.008 s, the flight to t=11.992 s, a 1 s hold)
  [PASS] manifest_version: manifest_version 1, spec cef57d752362381d
  [PASS] fields_finite: 48 frame records checked
  [PASS] geometry_recovery: 48 frames; quaternion-vs-euler reprojection gap 0.0000 px (tol 0.5); 0 aircraft behind camera; 0 aimed frames without the aircraft in frame
  [PASS] cross_view_consistency: 24 two-view instants; worst triangulation error 0.0000 m (tol 0.5)
  [PASS] count_exactness: 2 camera(s), every declared count met exactly
  [PASS] engine_parity: 48 frames across 2 camera(s); worst position 0.0xx m (tol 0.1); worst angle 0.0xx deg (tol 0.1); worst time x.xe-xx s (tol 1e-06; every instant on the 120 Hz grid, the engine stepped 0.008333 s, clock origin x.xxxxxx s); pose applied at the scheduled instant to 0.0e+00 s; worst reprojection x.xx px (tol 3.0); aircraft drawn within x.xx m of the manifest's aircraft (budget 2.08 m = 1.5 steps x 1.384 m/step at 166.0 m/s) and xx.x px of its labelled pixel (tol 26.3 px at that frame's 111 m); the engine measured its aircraft within xx.x px of the label and x.xx px of the manifest's projection model (tol 3.0); lowest label window contrast xx.x against background xxx.x (min 8)
verification PASSED (6/6 checks)
rendered 48 frames across 2 camera(s) (48 verified by engine parity) under runs\demo\frames
```

The `x` digits are the numbers this section exists to obtain; write
them in here from the log. What each one tells:

* `worst position` / `worst angle` -- the camera actor against the
  solved pose, both applied AT the scheduled instant, so these measure
  the engine's placement fidelity only (a transform clamp, a collision
  handler), never the clock; expected well under 0.01 m / 0.01 deg.
* `pose applied at the scheduled instant to 0.0e+00 s` -- exact by
  construction (`t_pose_s` is the card's instant); anything else means
  the commandlet regressed to applying the pose at the clock.
* `worst time` -- the RUN clock at the capture (`simulation/sim-time-sec`
  minus `clock_origin_s`, the reading before the first step) against
  the scheduled instant: expected at float accumulation, under 1e-9 s
  (1439 steps of 0.0083333 s). The one-step ambiguity of the previous
  contract is gone by construction: whatever the trim sequence or
  engine start left on the clock is `clock_origin_s` (printed in the
  line; expected 0.000000 or a small multiple of 0.008333), subtracted,
  and recorded -- it can never make a capture "one step late but
  within contract". A value over 1e-6 s fails by name and means the
  schedule is not on the engine's grid, which the log's "clock origin"
  and the pass's `step_s` then explain.
* `the engine measured its aircraft within xx.x px of the label` -- the
  commandlet's own projection of the actor it drew against the
  manifest's labelled pixel; expected within the same graded budget as
  the drawn-aircraft clause (the same point, two projections), and
  `x.xx px of the manifest's projection model` expected under 0.1 px
  (one lens, two formulae).
* `lowest label window contrast` -- the first number ever measured on
  rendered pixels for this clause: the darkest-against-its-background
  aircraft window across the 48 frames. Expected well above 8 for a
  747 against sky or ground; a value near 0 with the aircraft visible
  on screen means the label window is not where the aircraft is, and
  the frame's `aircraft_bbox_px` says where the engine drew it.
* `aircraft drawn within x.xx m` -- the engine's own FDM against the
  headless flight at the capture: ONE expected number, about 1.38 m
  for this example (the measured constant one-step host phase,
  docs/VALIDITY.md, at 1.384 m/step), against the printed budget of
  2.08 m = 1.5 steps x 1.384 m/step. There is no clock-offset term any
  more: the time clause above refuses an offset clock by name, so a
  value over the budget is a diverged FDM (or a wrong trim state), not
  a coupling.

### 3. The two commandlet passes, literally

What step 2 runs (the command builder is
`core.capture.render_pass.render_command`; substitute the checkout
path). The mesh argument is present only once the B747 model is
imported (`assets\generated\B747\mesh_manifest.json`; the owner's
placeholder rule refuses `aircraft.mesh` otherwise):

```
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" C:\flightsim\ue\FlightSim.uproject -run=FlightSimBridge.FlightSimRender -scenario=C:\flightsim\runs\demo\card.json -frames=C:\flightsim\runs\demo\frames\chase0 -Visual -shot=showcase -camera-index=0 -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -unattended -nopause -nosplash -stdout -FullStdOutLogOutput -RenderOffScreen -AllowCommandletRendering -mesh=C:\flightsim\assets\generated\B747\mesh_manifest.json -telemetry=C:\flightsim\runs\demo\engine_telemetry.json
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" C:\flightsim\ue\FlightSim.uproject -run=FlightSimBridge.FlightSimRender -scenario=C:\flightsim\runs\demo\card.json -frames=C:\flightsim\runs\demo\frames\tower0 -Visual -shot=showcase -camera-index=1 -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -unattended -nopause -nosplash -stdout -FullStdOutLogOutput -RenderOffScreen -AllowCommandletRendering -mesh=C:\flightsim\assets\generated\B747\mesh_manifest.json
```

Each pass's editor log lands in `runs\demo\frames\<camera_id>\render.log`
and MUST contain, in this order (the `%d`/`%.3f` values are the
example's):

```
consume-poses: camera 0 of 2, 115 solved samples
consume-poses: 24 scheduled captures from t=0.008 s to t=11.992 s; 1280x720 px, sensor 36.00 x 20.25 mm, focal 35.0 mm (fov 54.43 deg)
stepping 1440 steps of 0.008333 s, capturing at 24 scheduled instants at 1280x720
consume-poses: clock origin t=0.000000 s before the first step; capture times are run-relative
consume-poses: stopped after the last scheduled instant at t=11.992 s (1439 of 1440 steps)
consume-poses: captured 24 of 24 scheduled frames
wrote 24 frames and C:\flightsim\runs\demo\frames\chase0\render.json
```

The "stopped after" line is the frames-mode editor-time guard: the
pass steps to the last scheduled instant and no further (1439 steps
here; a 120 s spec whose 24 captures lie in its first 12 s costs the
same 1439, not 14400). The Python side reports the recorded
`steps_taken`/`stepped_s` per pass, as above.

(camera 1 of 2 for the tower pass). `-fps=30` is passed and ignored in
this mode: the log must NOT say "capturing every 4 (30.0 Hz)". Absent
lines, or "captured 23 of 24", are a failed pass and the Python side
fails the run as `render.frames`.

### 4. Expected tree and counts

```
runs\demo\
  capture_manifest.json        48 frame records, file = frames/<id>/NNNN.png
  card.json                    cameras: 2 blocks, 115 poses each, 24 capture_times_s each
  frames\chase0\0000.png .. 0023.png   24 files, 1280x720
  frames\chase0\render.json    frames_scheduled 24, frames_captured 24, step_s 0.008333, clock_origin_s, steps_taken 1439, stepped_s 11.992, 24 frame_records with frame_index 0..23 (each with t_scheduled_s, t_applied_s, t_clock_s, t_pose_s, camera_applied_*, camera_solved_*, aircraft_applied_*, aircraft_px, aircraft_py, aircraft_visible, aircraft_bbox_px)
  frames\chase0\render.log
  frames\tower0\0000.png .. 0023.png   24 files
  frames\tower0\render.json    the same, camera_index 1
  frames\tower0\render.log
  frames\chase0\clip_playlist.ffconcat   the lead-in first ('../clip_lead.png', 0.008333 s), then 0000.png .. 0023.png with their durations, 0023.png repeated
  frames\clip_lead.png         the by-product clip's black lead-in, 1280x720 (beside the camera directories, never inside one)
  clip.mp4                     the by-product: black to t=0.008 s, 24 frames at their instants to t=11.992 s, the last held 1 s: 12.992 s
  run.json                     spec_digest, output_digest, samples 115, render {choice "frames", label "Render frames and clip", engine_available true, engine_unavailable_reason null}, render_passes (per camera: scheduled 24, rendered 24, steps_taken 1439, stepped_s 11.992), clip_encoded true, clip_seconds 12.992
  verify.json                  the verifier's report as run (the JSON the webapp serves): ok, checks [6, each name/ok/status/detail/data], passed 6, ran 6, awaiting [] -- rewritten after the passes, so the printed table and the file agree without re-running
  previews\chase0\preview_00000.png .. preview_00023.png   24 geometry previews at 1280x720 (not frames); the same for tower0
  contact_sheets\chase0.png, tower0.png   one contact sheet per camera
  overlays\chase0\0000.png .. 0023.png   24 overlays, 1280x720: the manifest's geometry drawn over the rendered frame; the same for tower0
  engine_telemetry.json        the engine's own recorder, pass 0
  telemetry.json               the headless flight the manifest describes
```

`dir /b runs\demo\frames\chase0\*.png | find /c ".png"` must print 24.

### 5. The verifier over the rendered frames

```
.venv\Scripts\python -m flightsim.verify runs\demo
```

must print the six `[PASS]` lines of step 2 and exit 0; the
`engine_parity` line is the phase's engine-parity claim, and its
numbers go into this document. Then the failure demonstrations, each
of which must FAIL by name:

* edit `runs\demo\frames\chase0\render.json`, add 0.2 to one record's
  `camera_applied_north_m`: `[FAIL] engine_parity: chase0 frame N:
  applied position 0.200 m from the solved pose (tol 0.1)`;
* delete `runs\demo\frames\tower0\0005.png`: `[FAIL] engine_parity:
  tower0 frame 5: frames/tower0/0005.png does not exist`;
* edit `runs\demo\frames\chase0\render.json`, add 5.0 to one record's
  `aircraft_applied_east_m`: `[FAIL] engine_parity: chase0 frame N: the
  engine drew the aircraft 5.00 m from the manifest's aircraft (budget
  2.08 m = 1.5 steps x 1.384 m/step at 166.0 m/s, 120 Hz), 5x.x px from
  its labelled pixel (tol 2x.x px at 1xx m)` -- the metre budget of THIS
  run, with its arithmetic; the same edit on a tower record fails on the
  metres at 3.8 px;
* edit `runs\demo\frames\chase0\render.json`, add 0.008333 to one
  record's `t_applied_s`: `[FAIL] engine_parity: chase0 frame N:
  captured at t=... s against the scheduled ... s (tol 1e-06)` -- one
  step late is a different FDM state and fails by name, never absorbed;
  set the root's `step_s` to 10.0: `chase0: the engine stepped 10 s
  against the spec's 120 Hz (1/120 = 0.008333 s); the frames are not on
  the manifest's grid` -- the tolerance comes from the manifest, never
  from the file being judged;
* edit `card.json`, add 0.003 to one entry of camera 0's
  `capture_times_s`, re-run pass 0: the commandlet must refuse at that
  step with `consume-poses: scheduled instant t=... s (frame N) is not
  on the fixed-step grid: the run clock stepped past it to ... s (step
  0.008333 s, clock origin ... s)`; the Python side refuses the same
  schedule earlier, at solve time (`camera.schedule: camera 'chase0'
  schedules 1 instant(s) off the 120 Hz fixed-step grid`), so the
  engine's refusal is reachable only by editing the card;
* run `examples\cameras_multi.yaml` with `turbulence: moderate` and
  `--render frames`: `REFUSED render.host_parity: turbulence 'moderate':
  same-seed host parity is measured and refused ...` before any flight
  (exit 2); `--render clip` on the same spec renders the visual-only
  clip;
* replace `runs\demo\frames\tower0\0007.png` with a flat PNG of the
  same size (`.venv\Scripts\python -c "from PIL import Image;
  Image.new('RGB', (1280, 720), (30, 30, 30)).save(r'runs\demo\frames\tower0\0007.png')"`):
  `[FAIL] engine_parity: tower0 frame 7: nothing is drawn at the
  labelled pixel of frames/tower0/0007.png: label window [...] mean 30.0
  std 0.0 against background mean 30.0 std 0.0, contrast 0.0 (min 8)` --
  the pixel-content clause; restore the frame afterwards;
* edit `runs\demo\frames\tower0\render.json`, add 40 to one record's
  `aircraft_px`: `[FAIL] engine_parity: tower0 frame N: the engine
  measured the aircraft at (x, y) px, 40.0 px from the labelled pixel
  (x, y) (tol ~4 px)` -- the engine's own projection against the label;
  set the same record's `aircraft_visible` to false: `the engine reports
  the aircraft not visible in a frame whose label places it at ...`;
* edit `runs\demo\frames\chase0\render.json`, add 0.008333 to one
  record's `t_pose_s`: `[FAIL] engine_parity: chase0 frame N: pose
  applied at t=... s against the scheduled ... s (tol 1e-06): the pose
  must be applied at the scheduled instant, not the engine clock`;
* re-run pass 1 with `-seconds=6` appended: the commandlet must refuse
  before stepping with `consume-poses: camera 1 schedules a capture at
  t=11.992 s but the run is 6.000 s long; the run does not cover the
  schedule`;
* edit `card.json`, drop the last 20 entries of camera 0's
  `poses.t_s`/`north_m`/... arrays, re-run pass 0: `consume-poses: the
  schedule spans t=0.008..11.992 s but the solved track covers only
  0.008..x s; the track does not cover the run`.

### 5b. The by-product clip, measured

The clip's ffmpeg argv is pinned by test and UNMEASURED here (no
ffmpeg on the authoring machine). On the Windows machine:

```
ffprobe -v error -show_entries format=duration -of csv=p=0 runs\demo\clip.mp4
ffprobe -v error -select_streams v -count_frames -show_entries stream=nb_read_frames,width,height -of csv=p=0 runs\demo\clip.mp4
```

The first must print 12.992 to within one frame of the last-held
instant (12.99); the second 25 read frames (the lead-in plus 24) at
1280x720 -- write both numbers here. A duration off by the 0.008 s
lead-in or by the 1 s hold means the concat demuxer dropped an entry
and the playlist, not the frames, is at fault.

### 5c. The overlays, looked at (NOT YET RUN)

The overlays are the verification made visible, and they have only
ever been drawn over the honest engine STUB here. On the Windows
machine, after step 2:

```
dir /b runs\demo\overlays\chase0\*.png | find /c ".png"
start runs\demo\overlays\chase0\0005.png
start runs\demo\overlays\tower0\0010.png
```

The count must print 24 (and 24 for tower0). In `chase0\0005.png` the
yellow wing line (64.5 m at 176 m range: 455 px wide) must lie across
the rendered 747's wings and the box enclose the fuselage, to within
the frame's graded pixel budget the verifier prints ("aircraft drawn
within x.xx m", about 10 px at this range); the horizon line must run
along the rendered horizon (the flat scene's ground plane edge) and the
lattice recede toward it. In `tower0\0010.png` the aircraft is 3 km
away: a 26 px span line on the rendered aircraft, the track line along
its path, no horizon in frame (the tower looks up 75 deg). A wing line
beside, not on, the rendered aircraft is the SAME disagreement engine
parity grades numerically, and the frame's `render.json` record says
which side (`aircraft_px` against the manifest's labelled pixel); a
horizon line off the rendered horizon is an orientation disagreement
the applied-vs-solved clause would already have failed. Write here
what was seen.

### 6. The same from the page

Start the server, interpret "fly the 747 at 10000 ft and 280 kt for 12
seconds with a chase camera and a tower camera capturing 24 images",
leave the render select on *Render frames and clip* (the default once
the bridge is built) and Run. The status lines must read, in order,
"scheduled 48 frame(s) across 2 camera(s)", "editor pass 1 of 2: camera
'chase0', 24 frames scheduled over the 12 s run", "camera 'chase0': 24
of 24 scheduled frames rendered", the same for 'tower0', "encoding the
by-product clip from camera 'chase0'", "verification PASSED (6/6
checks)", and finally "48 frames across 2 camera(s) rendered (48
scheduled, 48 verified by engine parity) + clip (by-product of
'chase0')". The page's capture card must show "48 scheduled, 48
rendered, 48 verified", list `capture/frames/chase0` and
`capture/frames/tower0` as 24 rendered frames each, and
`/runs/<id>/bundle.zip` must contain the 48 PNGs.

### 7. Temporal alignment on rendered frames

```
.venv\Scripts\python -m flightsim.capture examples\cameras_multi.yaml --out runs\demo_b --render frames
.venv\Scripts\python -m flightsim.verify runs\demo_b --against runs\demo
```

with `examples\cameras_multi.yaml` edited to a single cockpit camera
capturing 24 images (see `tests/test_camera_cli.py::
test_two_camera_sets_align_in_time` for the exact edit): the
`temporal_alignment` line must pass with identical `simulation_digest`
and `output_digest` and 24 aligned instants, now on rendered frames.

Paste every log back; this section is rewritten from them.

## Known limitations

* Keyframed moves only — no physically simulated camera platforms (out
  of scope by the phase definition).
* The headless CLI's tornado hazard check uses the straight-line
  45%-ahead placement (its own track IS straight); the webapp's
  terrain runs refine the placement onto the pre-flown banked track
  through the same shared helper.
* Cross-view consistency is honestly reported NOT EXERCISED for
  single-camera runs (no false pass, no false failure).
* **The engine pass is NOT YET RUN.** The consume-poses C++ (schedule-
  driven capture, index naming, applied + solved pose per frame,
  orientation parity, the count contract, the lens from the card) was
  written in an environment with no engine and no compiler; the Python
  side is exercised against an honest engine STUB that writes what the
  contract specifies. Until the Windows section above has been run and
  its log read, engine parity has never been exercised on real pixels,
  and this document says so rather than counting it.
* The by-product clip's ffmpeg concat encoding is unmeasured here (no
  ffmpeg on the authoring machine); its argv, playlist, lead-in PNG and
  expected length are pinned by test, and step 5b above is the ffprobe
  measurement. The panel clip stays with *Clip only*.
* A frames pass steps the editor to its LAST SCHEDULED INSTANT and
  stops (recorded as `steps_taken` / `stepped_s` per pass); a schedule
  whose last instant lies late in a long spec still steps to it -- 24
  captures spread over a 120 s spec is 14400 steps per camera pass --
  and the status line says how many. The 22 s cap applies to clips
  only; there is no frames-mode cap, by design: the schedule is the
  contract.
* The geometry preview's aircraft is a three-axis body and a box, not
  a silhouette, and its LENGTH is the FDM's wing-to-tail arm plus one
  mean chord (40.8 m for the B747, whose fuselage is 70.7 m) because
  JSBSim states no nose-to-tail length; the header and the manifest
  say exactly which metric each dimension is. The span (metrics/bw-ft)
  is the airframe's own.
* The overlays have been drawn over the honest engine stub only; over
  real rendered pixels they are NOT YET RUN (step 5c above).
* Terrain scenes have no distance rings or north arrow (the wireframe
  and the horizon carry the scale there); flat scenes have both.
* Segmentation masks, bounding boxes, domain randomization, batch
  execution: out of scope, untouched.
