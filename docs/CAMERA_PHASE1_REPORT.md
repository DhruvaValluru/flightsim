# Camera Phase 1 — Camera Control and Capture Geometry: report

What was implemented, how to demonstrate it, and what remains. Written
against the phase plan ("Phase 1 — Camera Control and Capture
Geometry") as it landed on this tree.

## Status today (2026-09-05)

What runs on which platform, per deliverable. "Measured here" is this
session's Linux x86_64 machine (no engine, no ffmpeg), with the test
that keeps the claim fresh; "stub" is the honest engine stub
(`tests.test_camera_cli.honest_cli_engine`: the consume-poses pass as
a Python function writing what the contract specifies); "NOT YET RUN"
means no real engine has ever produced it, and the section named holds
the exact steps and expected numbers. Nothing in the right-hand column
is counted as verified until the Windows logs have been pasted back.
`ci.yml` runs the suite on ubuntu, windows and macos runners (the
expected-output comparison masks numbers off the measured platform);
no CI result was read in this session.

| deliverable | without the engine (Linux; macOS or Windows before the build) | Windows with the engine (UE 5.5 + the built bridge) |
|---|---|---|
| prompt -> spec -> validate; cameras in the spec, digest, review table, refusals by name | measured here 2026-09-05 (`tests/test_camera_spec.py`, `test_camera_validate.py`, `test_llm_compiler.py`) | the same Python; nothing engine-side |
| headless capture: pose tracks, schedule, manifest, previews, contact sheets, `flightsim.verify` (`--render none`) | measured here 2026-09-05: 16 blocks below, exact to the digit on Linux x86_64 (`test_the_documents_expected_output_matches_a_fresh_run`) | the same command prints the same words; digits differ by bits (the comparison is masked there) |
| `--render frames`: one consume-poses pass per camera, `frames/<id>/NNNN.png` | stub, measured here 2026-09-05: the generated block in section 2 (48 frames, 1439 steps per pass; the wall time is the block's own, about 15 s), with every stub the child applies named in its preamble | NOT YET RUN -- sections 1-4 |
| `engine_parity` on rendered pixels (applied vs solved pose, capture clock, reprojection, drawn aircraft, label contrast) | stub: 48 of 48 verified, every measured value 0 (the stub draws where the label says); the row's digits are masked `x` in section 2 | NOT YET RUN -- section 5 (the x digits) |
| overlays over rendered frames (`overlays/<id>/NNNN.png`) | stub: 48, measured here 2026-09-05 (the s/frame is the block's own, about 0.17) | NOT YET RUN -- section 5c (looked at, not only counted) |
| the by-product clip of camera 0 (ffmpeg concat at the scheduled instants, 12.992 s) | argv, playlist and lead-in pinned by test; no ffmpeg on this machine, so never encoded here (the stub block's `clip:` line is the playlist arithmetic over a 3-byte placeholder) | NOT YET RUN -- section 5b (ffprobe: duration and 25 read frames) |
| `--render clip` / *Clip only* (the preset pass, an fps clip) | stub, measured here (`test_render_clip_is_the_single_preset_pass`) | observed on the user's Windows machine before 2026-09-03 on the PRE-REWRITE page flow (a clip plus schematic previews: analysis/PLAN_camera_frames_not_clip.md); the flow as it stands today NOT re-run there -- section 6 |
| the page's frames flow: galleries per camera, "N scheduled, M rendered, K verified", download classes, parity captions | measured here 2026-09-05 under node and the TestClient on the stub (`tests/test_webapp_capture.py`) | NOT YET RUN -- section 6 (6b, 6c for the failure and refusal words) |
| temporal alignment across two camera sets on rendered frames | measured here on headless runs (block 4 below: 24 instants, worst gap 0 s) | NOT YET RUN -- section 7 |
| the C++ consume-poses pass itself (`FlightSimRenderCommandlet.cpp`) | compile-safe by inspection only: never compiled, never run (no engine here) | NOT YET RUN -- section 1 (the build; paste the log back if it fails) |

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
  (a ray through each record's own label, cast from the pose
  RECOMPUTED from the spec over the telemetry, must meet the other's
  at the telemetry's aircraft -- commands round 3; a ray cast from the
  record under test through that record's own label passes through
  its aircraft whatever the pose, which is why round 2's formulation
  could see disagreeing aircraft states and never a moved camera),
  flight fidelity (every record's instant and aircraft state against
  `telemetry.json` at its sample, the file's digest against the
  manifest's `output_digest`; commands round 2), schedule fidelity (the
  schedule recomputed from `scenario.yaml`'s cameras over the
  telemetry, instant for instant; round 2), pose fidelity (every
  record's position, quaternion, Euler angles, focal length, fx/fy,
  principal point, resolution, sensor and clip planes against the
  pose track recomputed from `scenario.yaml`'s cameras over the
  telemetry at the record's sample, and every camera block's
  `pose_track_digest` against the recomputed track's, verbatim; round
  3), aim fidelity (the telemetry's aircraft put through each record's
  own pose must land where the preset's promise predicts: the image
  centre for an explicit camera, the pixel the 0.25 s lagged aim
  recomputed over the telemetry predicts for chase/wingman/tower/
  ground, the body-axis cg pixel for a cockpit -- the schedule table's
  `off-aim px` column, graded; round 3), and
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
./scripts/mutation_check.sh                # all guards

.venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo
.venv/bin/python -m flightsim.verify runs/demo
.venv/bin/python -m flightsim.capture examples/cameras_multi_cockpit.yaml --out runs/demo_b
.venv/bin/python -m flightsim.verify runs/demo_b --against runs/demo
.venv/bin/python -m flightsim.verify runs/demo --corrupt quaternion   # and aircraft, time, count, clock, flight, schedule, pose, lens
.venv/bin/python -m flightsim.verify runs/demo --corrupt flight       # the aircraft moved in EVERY view: only telemetry.json tells
.venv/bin/python -m flightsim.verify runs/demo --corrupt pose         # a camera moved 5 m, everything else consistent: only the pose recomputed from scenario.yaml tells
```

Both commands print the same kind of report (`flightsim/report.py`),
in this order: a **header** (spec, simulation and output digests; the
scene -- flat, or the raster's path and SHA-256 -- and CRS; the flight:
aircraft, the spec's duration and fixed-step rate, then the telemetry
window the schedule lives in, from the record itself -- "telemetry t
4.900..34.858 s (280 samples, 0.108 s apart), the clock at 4.900 s when
the record began (trim and engine start)" for the c172p, whose starter
crank steps the FDM before the record -- and the span; one line
per camera whose `aim` states the reference the aircraft's pixel is
promised against: "aim aircraft (lag 0.25 s: the pixel trails the
aircraft)" for the chase, wingman, tower and ground presets, "aim
aircraft (exact)" for an explicit camera, and for a cockpit "aim body
axis" with a second line saying that `aim_mode aircraft` is not applied
by the preset, where the cg sits relative to the lens and which pixel
that is ("(743.7, 691.9), (+103.7, +331.9) px from the image centre"
for the shoulder camera's 6 m ahead, 1.6 m below, 0.5 m right); the
schedule table's last column, `off-aim px`, is each frame's aircraft
pixel measured against that promise -- 0.0 for every shoulder frame,
up to 22.2 px for the chase (the aim lag), `-` for a point or bearing
aim -- so a pixel 332 px below centre is explained on the page it
appears on, or would stand out as a number -- and since round 3 the
`aim_fidelity` row GRADES that column: the aircraft's pixel through
each record against the pixel the promise predicts, to 1e-6 px ("48
records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted
22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7");
one line
per camera: id, preset/position mode, aim, resolution, focal length in
mm and pixels, capture count and trigger); for capture, **one line
naming where JSBSim's console went** (`<out>/jsbsim.log`, with the
number of model constructions routed there -- the startup banner JSBSim
prints from C++ on every construction is redirected at the file
descriptor level, `core/fdm/console.py`, so nothing of it reaches
stdout and nothing is lost); a **per-camera table of scheduled
instants** (index, simulation time, telemetry sample, camera position,
the aircraft's pixel through the verifier's own projection; `--brief`
collapses each camera to one line that states the spacing -- "every
0.5 s"; for a distance, proximity or event trigger the cause from the
trigger itself ("every 400 m of track; instants 6.600..7.433 s apart");
for a count or period schedule the range with "sample-snapped, not
uniform" -- never a period that was not measured); the **verification table** (`CHECK
STATUS MEASURED TOLERANCE WHERE`, one row per check, the WHERE column
naming the worst frame, sample or run), a `detail:` block ONLY for
the rows that did not PASS (`[FAIL] name: what was found`, `[SKIPPED]`
and `[AWAITING]` with their reasons; a PASS is rendered once, in the
table -- round 2; every check's prose, PASS included, is in
`verify.json`), the summary, and a **verdict line** whose first word
is the exit code's word. `--json` prints the
document the text was rendered from, as data (header, schedule,
previews, verification -- `VerificationReport.to_dict()`, the same JSON
written as `verify.json` and served by the page -- artefact paths, the
render choice, the JSBSim log, the exit code, and the text lines).

### Exit codes (one table for both commands)

| code | word on the verdict line | meaning |
|---|---|---|
| 0 | `done:` (capture) / `verified:` (verify) | what was asked was produced; every check that ran passed |
| 1 | `FAILED capture.verification:` / `FAILED verification:` | the verifier failed the artefact: a check FAILED; the table names it and where |
| 2 | `REFUSED [constraint]` / `REFUSED constraint:` | a named constraint refused before or while producing (`camera.*`, `ue.platform`, `render.host_parity`, `preview.scale`); a frames or clip engine pass that did not honour its contract ends `FAILED render.frames:` / `FAILED render.clip:` with the same code (the frames written are not a frame set) |
| 3 | `USAGE:` | the command line is wrong, a spec or run path does not exist (`USAGE: examples/nope.yaml: no such file`, no traceback), the run directory holds nothing to verify, or a `--corrupt` kind the run cannot carry; the line prints ONCE, on stdout, with argparse's usage text alone on stderr |
| 4 | `UNEXPECTED <Exception>:` | an exception; the traceback is on stderr |

`python -m flightsim.capture --help` and `flightsim.verify --help` print
the table. A check that had nothing to grade is **SKIPPED** with its
reason (cross-view consistency on a single camera), a check the machine
cannot exercise is **AWAITING** (engine parity without engine frames);
neither is a pass, neither counts in `passed` or `ran`, and the summary
names both ("4/4 checks; 1 skipped: cross_view_consistency (single
camera); 1 awaiting engine frames: engine_parity").

### Expected output of every committed example, verbatim

Without the engine the default render choice resolves to `none`, so
`--render none` is what the commands below ran with. Every block is the
command's stdout as run here, unedited; the JSBSim banner needs no
"omitted" caveat because it is in `runs/<run>/jsbsim.log` -- and so,
since docs round 1 (2026-09-05), is the Mass Properties Report the run
card's engine-start probe makes JSBSim print on the `--card` and
`--render frames` paths (the blocks below take neither; the Windows
block in "Engine verification" does, and was measured clean at the
file-descriptor level).

<!-- examples_expected: begin -->
Measured 2026-09-05 on Linux x86_64, Python 3.11.15 by `scripts/examples_expected.py` (every block below is the command's stdout verbatim, paths normalised to `runs/...`; wall times are this machine's, previews at full resolution). `tests/test_camera_cli.py::test_the_documents_expected_output_matches_a_fresh_run` regenerates the blocks and compares them with these: on Linux x86_64 exactly -- every digest, check number, pixel coordinate and camera position at its printed precision, only the wall-clock seconds per frame and the engine-availability line masked; on another platform with digests and numbers masked too, because the JSBSim build differs by bits there.

#### capture: two cameras, one flight (cameras_multi)

`python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo` -- exit 0, 5.18 s wall

```
spec cef57d752362381d valid; running headlessly...
run:         runs/demo
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
JSBSim output: runs/demo/jsbsim.log (14 model loads; nothing of JSBSim's on stdout)
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  manifest: runs/demo/capture_manifest.json
  previews: 48 geometry preview(s) at 1280x720, 0.075 s/frame under runs/demo/previews (previews are not frames; track: telemetry 9.23077 Hz (115 points, no decimation))
  contact sheets: 2 (contact_sheets/<camera_id>.png, one per camera)
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  PASS      1.04e-12 m                     0.5 m                         24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification PASSED (9/9 checks; 1 awaiting engine frames: engine_parity)
engine absent: no engine on this OS: the render half needs macOS, or Windows with Unreal Engine 5.5 and the FlightSimBridge built; frames not rendered (--render frames where the engine exists)
done: manifest, 48 previews and verification for 48 scheduled frames under runs/demo (no pixels)
```

#### verify: the same run, graded from its directory

`python -m flightsim.verify runs/demo` -- exit 0, 0.50 s wall

```
run:         runs/demo
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  PASS      1.04e-12 m                     0.5 m                         24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification PASSED (9/9 checks; 1 awaiting engine frames: engine_parity)
verified: runs/demo/capture_manifest.json (48 frame records, 2 camera(s)); report runs/demo/verify.json
```

#### capture: the same flight, a cockpit camera (cameras_multi_cockpit)

`python -m flightsim.capture examples/cameras_multi_cockpit.yaml --out runs/demo_b` -- exit 0, 2.84 s wall

```
spec b8e463be7defdc73 valid; running headlessly...
run:         runs/demo_b
spec         b8e463be7defdc73   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      1
  shoulder  cockpit/offset  aim body axis  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
            (aim_mode aircraft is not applied by the cockpit preset: the view is along the body axis; the cg sits 6 m ahead, 1.6 m below and 0.5 m right of the lens, so its pixel is (743.7, 691.9), (+103.7, +331.9) px from the image centre)
JSBSim output: runs/demo_b/jsbsim.log (14 model loads; nothing of JSBSim's on stdout)
scheduled 24 frames across 1 camera(s)
  shoulder: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0        -6.063       -0.500    3049.342  (743.7, 691.9)             0.0
       1     0.525       5        79.763       -0.500    3049.343  (743.7, 691.9)             0.0
       2     1.067      10       169.742       -0.500    3049.344  (743.7, 691.9)             0.0
       3     1.608      15       259.721       -0.500    3049.346  (743.7, 691.9)             0.0
       4     2.142      20       348.315       -0.499    3049.346  (743.7, 691.9)             0.0
       5     2.683      25       438.294       -0.499    3049.346  (743.7, 691.9)             0.0
       6     3.225      30       528.273       -0.499    3049.347  (743.7, 691.9)             0.0
       7     3.767      35       618.252       -0.498    3049.348  (743.7, 691.9)             0.0
       8     4.283      40       704.078       -0.498    3049.349  (743.7, 691.9)             0.0
       9     4.783      45       787.135       -0.497    3049.349  (743.7, 691.9)             0.0
      10     5.283      50       870.192       -0.497    3049.350  (743.7, 691.9)             0.0
      11     5.783      55       953.250       -0.496    3049.350  (743.7, 691.9)             0.0
      12     6.183      59      1019.696       -0.496    3049.350  (743.7, 691.9)             0.0
      13     6.683      64      1102.753       -0.495    3049.351  (743.7, 691.9)             0.0
      14     7.183      69      1185.810       -0.494    3049.351  (743.7, 691.9)             0.0
      15     7.683      74      1268.868       -0.493    3049.351  (743.7, 691.9)             0.0
      16     8.200      79      1354.694       -0.492    3049.351  (743.7, 691.9)             0.0
      17     8.742      84      1444.673       -0.491    3049.352  (743.7, 691.9)             0.0
      18     9.283      89      1534.651       -0.490    3049.352  (743.7, 691.9)             0.0
      19     9.825      94      1624.630       -0.489    3049.352  (743.7, 691.9)             0.0
      20    10.367      99      1714.609       -0.488    3049.352  (743.7, 691.9)             0.0
      21    10.908     104      1804.588       -0.486    3049.352  (743.7, 691.9)             0.0
      22    11.450     109      1894.567       -0.485    3049.352  (743.7, 691.9)             0.0
      23    11.992     114      1984.546       -0.483    3049.352  (743.7, 691.9)             0.0
  manifest: runs/demo_b/capture_manifest.json
  previews: 24 geometry preview(s) at 1280x720, 0.073 s/frame under runs/demo_b/previews (previews are not frames; track: telemetry 9.23077 Hz (115 points, no decimation))
  contact sheets: 1 (contact_sheets/<camera_id>.png, one per camera)
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec b8e463be7defdc73
  fields_finite           PASS      0 non-finite of 24 records     0 non-finite                  24 records, 6 fields each
  geometry_recovery       PASS      1.61e-13 px                    0.5 px                        worst shoulder #6 t=3.225 s
  cross_view_consistency  SKIPPED   -                              -                             single camera
  count_exactness         PASS      24 frames = 24                 exactly 24                    shoulder 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   24 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst shoulder #0 t=0.008 s
  schedule_fidelity       PASS      0 of 24 instants differ        0 differ                      shoulder 24/24 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  24 records against the tracks recomputed from 1 camera(s) over 115 samples; digests = pose_track_digest; worst shoulder #0 t=0.008 s
  aim_fidelity            PASS      gap 4.53e-11 px, axes 0 deg    1e-06 px, 1e-06 deg           24 records; shoulder body-axis: off-aim up to 347.7 px, predicted 347.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera shoulder (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [SKIPPED] cross_view_consistency: NOT EXERCISED (single camera): no instant is seen by two cameras; capture two cameras on a shared schedule to verify cross-view consistency
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera shoulder (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification PASSED (8/8 checks; 1 skipped: cross_view_consistency (single camera); 1 awaiting engine frames: engine_parity)
engine absent: no engine on this OS: the render half needs macOS, or Windows with Unreal Engine 5.5 and the FlightSimBridge built; frames not rendered (--render frames where the engine exists)
done: manifest, 24 previews and verification for 24 scheduled frames under runs/demo_b (no pixels)
```

#### verify --against: temporal alignment across the two camera sets

`python -m flightsim.verify runs/demo_b --against runs/demo` -- exit 0, 0.30 s wall

```
run:         runs/demo_b
spec         b8e463be7defdc73   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      1
  shoulder  cockpit/offset  aim body axis  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
            (aim_mode aircraft is not applied by the cockpit preset: the view is along the body axis; the cg sits 6 m ahead, 1.6 m below and 0.5 m right of the lens, so its pixel is (743.7, 691.9), (+103.7, +331.9) px from the image centre)
against:     runs/demo (temporal alignment)
scheduled 24 frames across 1 camera(s)
  shoulder: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0        -6.063       -0.500    3049.342  (743.7, 691.9)             0.0
       1     0.525       5        79.763       -0.500    3049.343  (743.7, 691.9)             0.0
       2     1.067      10       169.742       -0.500    3049.344  (743.7, 691.9)             0.0
       3     1.608      15       259.721       -0.500    3049.346  (743.7, 691.9)             0.0
       4     2.142      20       348.315       -0.499    3049.346  (743.7, 691.9)             0.0
       5     2.683      25       438.294       -0.499    3049.346  (743.7, 691.9)             0.0
       6     3.225      30       528.273       -0.499    3049.347  (743.7, 691.9)             0.0
       7     3.767      35       618.252       -0.498    3049.348  (743.7, 691.9)             0.0
       8     4.283      40       704.078       -0.498    3049.349  (743.7, 691.9)             0.0
       9     4.783      45       787.135       -0.497    3049.349  (743.7, 691.9)             0.0
      10     5.283      50       870.192       -0.497    3049.350  (743.7, 691.9)             0.0
      11     5.783      55       953.250       -0.496    3049.350  (743.7, 691.9)             0.0
      12     6.183      59      1019.696       -0.496    3049.350  (743.7, 691.9)             0.0
      13     6.683      64      1102.753       -0.495    3049.351  (743.7, 691.9)             0.0
      14     7.183      69      1185.810       -0.494    3049.351  (743.7, 691.9)             0.0
      15     7.683      74      1268.868       -0.493    3049.351  (743.7, 691.9)             0.0
      16     8.200      79      1354.694       -0.492    3049.351  (743.7, 691.9)             0.0
      17     8.742      84      1444.673       -0.491    3049.352  (743.7, 691.9)             0.0
      18     9.283      89      1534.651       -0.490    3049.352  (743.7, 691.9)             0.0
      19     9.825      94      1624.630       -0.489    3049.352  (743.7, 691.9)             0.0
      20    10.367      99      1714.609       -0.488    3049.352  (743.7, 691.9)             0.0
      21    10.908     104      1804.588       -0.486    3049.352  (743.7, 691.9)             0.0
      22    11.450     109      1894.567       -0.485    3049.352  (743.7, 691.9)             0.0
      23    11.992     114      1984.546       -0.483    3049.352  (743.7, 691.9)             0.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec b8e463be7defdc73
  fields_finite           PASS      0 non-finite of 24 records     0 non-finite                  24 records, 6 fields each
  geometry_recovery       PASS      1.61e-13 px                    0.5 px                        worst shoulder #6 t=3.225 s
  cross_view_consistency  SKIPPED   -                              -                             single camera
  count_exactness         PASS      24 frames = 24                 exactly 24                    shoulder 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   24 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst shoulder #0 t=0.008 s
  schedule_fidelity       PASS      0 of 24 instants differ        0 differ                      shoulder 24/24 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  24 records against the tracks recomputed from 1 camera(s) over 115 samples; digests = pose_track_digest; worst shoulder #0 t=0.008 s
  aim_fidelity            PASS      gap 4.53e-11 px, axes 0 deg    1e-06 px, 1e-06 deg           24 records; shoulder body-axis: off-aim up to 347.7 px, predicted 347.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera shoulder (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  temporal_alignment      PASS      0 s                            1e-09 s                       24 instants in both runs; worst gap 0 s
  detail:
  [SKIPPED] cross_view_consistency: NOT EXERCISED (single camera): no instant is seen by two cameras; capture two cameras on a shared schedule to verify cross-view consistency
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera shoulder (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification PASSED (9/9 checks; 1 skipped: cross_view_consistency (single camera); 1 awaiting engine frames: engine_parity)
verified: runs/demo_b/capture_manifest.json (24 frame records, 1 camera(s)); report runs/demo_b/verify.json
```

#### capture: waypoint trigger, one camera (cameras_waypoint)

`python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/waypoint` -- exit 0, 1.32 s wall

```
spec b031d3e385b823b3 valid; running headlessly...
run:         runs/waypoint
spec         b031d3e385b823b3   simulation 73f5ad46d2817e24   output 9225ac5e7dcb7ada
scene        flat (no raster)   crs EPSG:32631
flight       c172p, 30 s at 120 Hz (step 0.008333 s); telemetry t 4.900..34.858 s (280 samples, 0.108 s apart), the clock at 4.900 s when the record began (trim and engine start); span 10.9 m
cameras      1
  survey  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  5 captures, distance
JSBSim output: runs/waypoint/jsbsim.log (9 model loads; nothing of JSBSim's on stdout)
scheduled 5 frames across 1 camera(s)
  survey: 5 scheduled instant(s) (every 400 m along the flown ground track (1716 m total), start included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     4.900       0       -28.000        0.000    1204.000  (640.0, 360.0)             0.0
       1    12.333      71       355.174      -13.244    1202.809  (636.7, 334.7)            25.5
       2    19.483     137       732.510     -121.104    1189.740  (634.3, 343.3)            17.7
       3    26.417     201      1021.586     -389.426    1161.131  (632.5, 347.9)            14.3
       4    33.017     262      1098.203     -773.430    1128.009  (631.0, 348.0)            15.0
  manifest: runs/waypoint/capture_manifest.json
  previews: 5 geometry preview(s) at 1280x720, 0.083 s/frame under runs/waypoint/previews (previews are not frames; track: telemetry 9.23077 Hz (280 points, no decimation))
  contact sheets: 1 (contact_sheets/<camera_id>.png, one per camera)
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec b031d3e385b823b3
  fields_finite           PASS      0 non-finite of 5 records      0 non-finite                  5 records, 6 fields each
  geometry_recovery       PASS      2.34e-13 px                    0.5 px                        worst survey #3 t=26.417 s
  cross_view_consistency  SKIPPED   -                              -                             single camera
  count_exactness         PASS      5 frames = 5                   exactly 5                     survey 5/5
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   5 records against 280 samples; digest 9225ac5e7dcb7ada = output_digest; worst survey #0 t=4.900 s
  schedule_fidelity       PASS      0 of 5 instants differ         0 differ                      survey 5/5 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  5 records against the tracks recomputed from 1 camera(s) over 280 samples; digests = pose_track_digest; worst survey #0 t=4.900 s
  aim_fidelity            PASS      gap 7.96e-13 px                1e-06 px, 1e-06 deg           5 records; survey aircraft-lagged: off-aim up to 25.5 px, predicted 25.5
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera survey (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [SKIPPED] cross_view_consistency: NOT EXERCISED (single camera): no instant is seen by two cameras; capture two cameras on a shared schedule to verify cross-view consistency
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera survey (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification PASSED (8/8 checks; 1 skipped: cross_view_consistency (single camera); 1 awaiting engine frames: engine_parity)
engine absent: no engine on this OS: the render half needs macOS, or Windows with Unreal Engine 5.5 and the FlightSimBridge built; frames not rendered (--render frames where the engine exists)
done: manifest, 5 previews and verification for 5 scheduled frames under runs/waypoint (no pixels)
```

#### capture: the refusal (cameras_refusal)

`python -m flightsim.capture examples/cameras_refusal.yaml --out runs/refused` -- exit 2, 0.29 s wall

```
run:         runs/refused
spec         0b69edf3b46b0386   simulation 7051fbaad128630f   output -
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s)
cameras      1
  buried  explicit/scene  aim aircraft (exact)  1280x720  35.0 mm (fx 1244.4 px)  every 1 s, interval
REFUSED -- by name:
  [camera.terrain_clearance] camera[0] 'buried': the stated placement sits inside or on the scene's terrain (checked over the whole run window) (requested -600 m AGL, limit 2 m AGL)
JSBSim output: runs/refused/jsbsim.log (4 model loads; nothing of JSBSim's on stdout)
REFUSED [camera.terrain_clearance]: nothing produced (the run directory holds jsbsim.log only)
```

#### verify --corrupt quaternion: geometry recovery must FAIL

`python -m flightsim.verify runs/demo --corrupt quaternion` -- exit 1, 0.51 s wall

```
corrupt quaternion: manifest copied to runs/demo_corrupt_quaternion; corrupted chase0 frame 3 (t=1.608 s) quaternion y += 0.05 (-0.042399 -> 0.007601); the Euler angles are untouched
  expected: [FAIL] geometry_recovery, exit 1
run:         runs/demo_corrupt_quaternion
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 464.7)           104.7
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       FAIL      124.7076 px                    0.5 px                        worst chase0 #3 t=1.608 s
  cross_view_consistency  FAIL      18.1254 m                      0.5 m                         24 two-view instants; worst sample 15 t=1.608 s (chase0 #3 with tower0 #3); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           FAIL      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  quaternion differs from the spec's track by 0.050000 at chase0 #3 t=1.608 s
  aim_fidelity            FAIL      gap 125 px                     1e-06 px, 1e-06 deg           the aircraft's pixel is 124.708 px from where the camera's promise puts it at chase0 #3 t=1.608 s (aircraft at (640.0, 464.7) px, promised (640.0, 340.0) px: aircraft-lagged, off-aim 104.7 px against a predicted 20.0)
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] geometry_recovery: 48 frames; quaternion-vs-euler reprojection gap 124.7076 px (tol 0.5) at chase0 #3 t=1.608 s; 0 aircraft behind camera; 0 aimed frames without the aircraft in frame
  [FAIL] cross_view_consistency: 24 two-view instants (rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft); worst triangulation error 18.1254 m (tol 0.5) at sample 15 t=1.608 s (chase0 #3 with tower0 #3)
  [FAIL] pose_fidelity: quaternion differs from the spec's track by 0.050000 at chase0 #3 t=1.608 s
  [FAIL] aim_fidelity: the aircraft's pixel is 124.708 px from where the camera's promise puts it at chase0 #3 t=1.608 s (aircraft at (640.0, 464.7) px, promised (640.0, 340.0) px: aircraft-lagged, off-aim 104.7 px against a predicted 20.0)
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (5/9 checks; FAILED: geometry_recovery, cross_view_consistency, pose_fidelity, aim_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt quaternion, geometry_recovery FAILED (also: cross_view_consistency, pose_fidelity, aim_fidelity); runs/demo_corrupt_quaternion/capture_manifest.json graded, report runs/demo_corrupt_quaternion/verify.json
```

#### verify --corrupt aircraft: cross-view consistency must FAIL

`python -m flightsim.verify runs/demo --corrupt aircraft` -- exit 1, 0.50 s wall

```
corrupt aircraft: manifest copied to runs/demo_corrupt_aircraft; corrupted tower0: every frame's recorded aircraft north_m += 5 m (24 frames); chase0's records are untouched, so the two views disagree
  expected: [FAIL] cross_view_consistency, exit 1
run:         runs/demo_corrupt_aircraft
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (638.7, 358.7)             1.9
       1     0.525       5       900.000     -800.000      80.000  (630.7, 350.9)            13.0
       2     1.067      10       900.000     -800.000      80.000  (629.2, 350.4)            14.4
       3     1.608      15       900.000     -800.000      80.000  (628.4, 350.9)            14.8
       4     2.142      20       900.000     -800.000      80.000  (627.6, 351.5)            15.0
       5     2.683      25       900.000     -800.000      80.000  (626.9, 352.4)            15.1
       6     3.225      30       900.000     -800.000      80.000  (626.3, 353.4)            15.2
       7     3.767      35       900.000     -800.000      80.000  (625.6, 354.7)            15.3
       8     4.283      40       900.000     -800.000      80.000  (625.0, 356.0)            15.6
       9     4.783      45       900.000     -800.000      80.000  (624.6, 357.4)            15.7
      10     5.283      50       900.000     -800.000      80.000  (624.3, 358.9)            15.7
      11     5.783      55       900.000     -800.000      80.000  (624.3, 360.5)            15.7
      12     6.183      59       900.000     -800.000      80.000  (624.4, 361.7)            15.7
      13     6.683      64       900.000     -800.000      80.000  (624.7, 363.2)            15.6
      14     7.183      69       900.000     -800.000      80.000  (625.1, 364.6)            15.6
      15     7.683      74       900.000     -800.000      80.000  (625.7, 365.9)            15.5
      16     8.200      79       900.000     -800.000      80.000  (626.4, 366.9)            15.2
      17     8.742      84       900.000     -800.000      80.000  (627.2, 367.9)            15.0
      18     9.283      89       900.000     -800.000      80.000  (628.0, 368.7)            14.8
      19     9.825      94       900.000     -800.000      80.000  (628.7, 369.3)            14.7
      20    10.367      99       900.000     -800.000      80.000  (629.4, 369.8)            14.5
      21    10.908     104       900.000     -800.000      80.000  (630.0, 370.2)            14.2
      22    11.450     109       900.000     -800.000      80.000  (630.6, 370.4)            14.0
      23    11.992     114       900.000     -800.000      80.000  (631.2, 370.6)            13.8
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  FAIL      5.1845 m                       0.5 m                         24 two-view instants; worst sample 0 t=0.008 s (chase0 #0 with tower0 #0); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         FAIL      t 0 s, pos 5 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   aircraft position differs from the telemetry by 5.000 m at tower0 #0 t=0.008 s (recorded aircraft 5.000 N, 0.000 E, 3048.000 m; telemetry 0.000 N, 0.000 E, 3048.000 m at sample 0)
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] cross_view_consistency: 24 two-view instants (rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft); worst triangulation error 5.1845 m (tol 0.5) at sample 0 t=0.008 s (chase0 #0 with tower0 #0)
  [FAIL] flight_fidelity: aircraft position differs from the telemetry by 5.000 m at tower0 #0 t=0.008 s (recorded aircraft 5.000 N, 0.000 E, 3048.000 m; telemetry 0.000 N, 0.000 E, 3048.000 m at sample 0)
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (7/9 checks; FAILED: cross_view_consistency, flight_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt aircraft, cross_view_consistency FAILED (also: flight_fidelity); runs/demo_corrupt_aircraft/capture_manifest.json graded, report runs/demo_corrupt_aircraft/verify.json
```

#### verify --corrupt time: temporal alignment must FAIL

`python -m flightsim.verify runs/demo --corrupt time` -- exit 1, 0.50 s wall

```
corrupt time: manifest copied to runs/demo_corrupt_time; corrupted chase0 frame 3 t_s += one fixed step (0.008333 s: 1.608333 -> 1.616667 s)
  expected: [FAIL] temporal_alignment, exit 1
run:         runs/demo_corrupt_time
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
against:     runs/demo (temporal alignment)
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.617      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                            TOLERANCE                     WHERE
  manifest_version        PASS      version 1                           = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records          0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                          0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  PASS      1.04e-12 m                          0.5 m                         24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24                 exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         FAIL      t 0.00833333 s, pos 0 m, att 0 deg  1e-09 s, 1e-06 m, 1e-06 deg   instant differs from the telemetry by 0.008333 s at chase0 #3 t=1.617 s (telemetry t=1.608333 s at sample 15)
  schedule_fidelity       FAIL      1 of 48 instants differ             0 differ                      1 of 48 instants differ from the spec's schedule; worst chase0 #3 at sample 15 t=1.617 s where the spec schedules sample 15 t=1.608 s
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px       1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                      1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                                   -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  temporal_alignment      FAIL      25 vs 24 instants                   1e-09 s                       25 instants in demo_corrupt_time vs 24 in demo; only in demo_corrupt_time: t=1.616667 s
  detail:
  [FAIL] flight_fidelity: instant differs from the telemetry by 0.008333 s at chase0 #3 t=1.617 s (telemetry t=1.608333 s at sample 15)
  [FAIL] schedule_fidelity: 1 of 48 instants differ from the spec's schedule; worst chase0 #3 at sample 15 t=1.617 s where the spec schedules sample 15 t=1.608 s
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  [FAIL] temporal_alignment: 25 capture instants in demo_corrupt_time against 24 in demo; only in demo_corrupt_time: t=1.616667 s
verification FAILED (7/10 checks; FAILED: flight_fidelity, schedule_fidelity, temporal_alignment; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt time, temporal_alignment FAILED (also: flight_fidelity, schedule_fidelity); runs/demo_corrupt_time/capture_manifest.json graded, report runs/demo_corrupt_time/verify.json
```

#### verify --corrupt count: count exactness must FAIL

`python -m flightsim.verify runs/demo --corrupt count` -- exit 1, 0.49 s wall

```
corrupt count: manifest copied to runs/demo_corrupt_count; corrupted chase0: frame record 23 (t=11.992 s) dropped; capture_count stays 24
  expected: [FAIL] count_exactness, exit 1
run:         runs/demo_corrupt_count
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 47 frames across 2 camera(s)
  chase0: 23 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 47 records     0 non-finite                  47 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  PASS      1.04e-12 m                     0.5 m                         23 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         FAIL      47 frames = 23 + 24            exactly 48                    chase0 23/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   47 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       FAIL      1 of 48 instants differ        0 differ                      chase0: 23 recorded instants against 24 the spec schedules
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  47 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           47 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] count_exactness: chase0: 23 frames against a declared 24 (missing index 23)
  [FAIL] schedule_fidelity: chase0: 23 recorded instants against 24 the spec schedules
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (7/9 checks; FAILED: count_exactness, schedule_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt count, count_exactness FAILED (also: schedule_fidelity); runs/demo_corrupt_count/capture_manifest.json graded, report runs/demo_corrupt_count/verify.json
```

#### verify --corrupt clock: flight fidelity must FAIL (every instant shifted, no sibling run)

`python -m flightsim.verify runs/demo --corrupt clock` -- exit 1, 0.50 s wall

```
corrupt clock: manifest copied to runs/demo_corrupt_clock; corrupted every record (48 frames, both the sample_index and the aircraft state untouched): t_s += 0.5 s; the records still agree with each other, only the telemetry's clock says otherwise
  expected: [FAIL] flight_fidelity, exit 1
run:         runs/demo_corrupt_clock
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.508       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     1.025       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.567      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     2.108      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.642      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     3.183      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.725      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     4.267      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.783      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     5.283      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.783      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     6.283      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.683      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     7.183      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.683      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     8.183      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.700      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     9.242      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.783      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19    10.325      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.867      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    11.408     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.950     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    12.492     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.508       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     1.025       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.567      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     2.108      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.642      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     3.183      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.725      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     4.267      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.783      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     5.283      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.783      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     6.283      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.683      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     7.183      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.683      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     8.183      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.700      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     9.242      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.783      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19    10.325      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.867      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    11.408     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.950     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    12.492     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=5.283 s
  cross_view_consistency  PASS      1.04e-12 m                     0.5 m                         24 two-view instants; worst sample 10 t=1.567 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         FAIL      t 0.5 s, pos 0 m, att 0 deg    1e-09 s, 1e-06 m, 1e-06 deg   instant differs from the telemetry by 0.500000 s at chase0 #1 t=1.025 s (telemetry t=0.525000 s at sample 5)
  schedule_fidelity       FAIL      48 of 48 instants differ       0 differ                      48 of 48 instants differ from the spec's schedule; worst chase0 #1 at sample 5 t=1.025 s where the spec schedules sample 5 t=0.525 s
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.508 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] flight_fidelity: instant differs from the telemetry by 0.500000 s at chase0 #1 t=1.025 s (telemetry t=0.525000 s at sample 5)
  [FAIL] schedule_fidelity: 48 of 48 instants differ from the spec's schedule; worst chase0 #1 at sample 5 t=1.025 s where the spec schedules sample 5 t=0.525 s
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (7/9 checks; FAILED: flight_fidelity, schedule_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt clock, flight_fidelity FAILED (also: schedule_fidelity); runs/demo_corrupt_clock/capture_manifest.json graded, report runs/demo_corrupt_clock/verify.json
```

#### verify --corrupt flight: flight fidelity must FAIL (the aircraft moved in every view; cross-view fails beside it since round 3)

`python -m flightsim.verify runs/demo --corrupt flight` -- exit 1, 0.50 s wall

```
corrupt flight: manifest copied to runs/demo_corrupt_flight; corrupted every camera's every record (48 frames): aircraft north_m += 50 m; the views still agree with EACH OTHER (cross_view_consistency passes), only the telemetry says the aircraft was elsewhere
  expected: [FAIL] flight_fidelity, exit 1
run:         runs/demo_corrupt_flight
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 317.9)            42.1
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 314.5)            45.5
       2     1.067      10         5.891        0.000    3060.001  (640.0, 319.2)            40.8
       3     1.608      15        91.530        0.000    3060.002  (640.0, 321.0)            39.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 321.4)            38.6
       5     2.683      25       268.383        0.001    3060.004  (640.0, 321.7)            38.3
       6     3.225      30       358.263        0.001    3060.004  (640.0, 321.7)            38.3
       7     3.767      35       448.213        0.001    3060.005  (640.0, 321.7)            38.3
       8     4.283      40       533.719        0.002    3060.006  (640.0, 321.6)            38.4
       9     4.783      45       616.554        0.002    3060.007  (640.0, 321.6)            38.4
      10     5.283      50       699.538        0.003    3060.007  (640.0, 321.6)            38.4
      11     5.783      55       782.571        0.003    3060.007  (640.0, 321.6)            38.4
      12     6.183      59       849.010        0.004    3060.008  (640.0, 321.6)            38.4
      13     6.683      64       932.064        0.005    3060.008  (640.0, 321.6)            38.4
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 321.6)            38.4
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 321.6)            38.4
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 321.7)            38.3
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 321.8)            38.2
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 321.8)            38.2
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 321.7)            38.3
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 321.7)            38.3
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 321.7)            38.3
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 321.7)            38.3
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 321.7)            38.3
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (627.0, 346.5)            18.7
       1     0.525       5       900.000     -800.000      80.000  (618.5, 338.9)            30.1
       2     1.067      10       900.000     -800.000      80.000  (616.2, 338.9)            31.8
       3     1.608      15       900.000     -800.000      80.000  (614.6, 340.0)            32.3
       4     2.142      20       900.000     -800.000      80.000  (613.0, 341.5)            32.7
       5     2.683      25       900.000     -800.000      80.000  (611.5, 343.4)            33.0
       6     3.225      30       900.000     -800.000      80.000  (610.0, 345.7)            33.2
       7     3.767      35       900.000     -800.000      80.000  (608.7, 348.4)            33.4
       8     4.283      40       900.000     -800.000      80.000  (607.4, 351.2)            33.7
       9     4.783      45       900.000     -800.000      80.000  (606.6, 354.3)            33.9
      10     5.283      50       900.000     -800.000      80.000  (606.2, 357.7)            33.9
      11     5.783      55       900.000     -800.000      80.000  (606.1, 361.0)            33.9
      12     6.183      59       900.000     -800.000      80.000  (606.3, 363.7)            33.9
      13     6.683      64       900.000     -800.000      80.000  (607.0, 367.0)            33.8
      14     7.183      69       900.000     -800.000      80.000  (607.9, 370.0)            33.6
      15     7.683      74       900.000     -800.000      80.000  (609.1, 372.7)            33.4
      16     8.200      79       900.000     -800.000      80.000  (610.6, 375.0)            33.0
      17     8.742      84       900.000     -800.000      80.000  (612.2, 377.1)            32.6
      18     9.283      89       900.000     -800.000      80.000  (613.8, 378.8)            32.2
      19     9.825      94       900.000     -800.000      80.000  (615.4, 380.2)            31.8
      20    10.367      99       900.000     -800.000      80.000  (616.9, 381.3)            31.4
      21    10.908     104       900.000     -800.000      80.000  (618.3, 382.1)            30.9
      22    11.450     109       900.000     -800.000      80.000  (619.7, 382.6)            30.4
      23    11.992     114       900.000     -800.000      80.000  (620.9, 383.0)            29.9
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  FAIL      50.0 m                         0.5 m                         24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         FAIL      t 0 s, pos 50 m, att 0 deg     1e-09 s, 1e-06 m, 1e-06 deg   aircraft position differs from the telemetry by 50.000 m at chase0 #1 t=0.525 s (recorded aircraft 135.826 N, 0.000 E, 3048.001 m; telemetry 85.826 N, 0.000 E, 3048.001 m at sample 5)
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] cross_view_consistency: 24 two-view instants (rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft); worst triangulation error 50.0000 m (tol 0.5) at sample 10 t=1.067 s (chase0 #2 with tower0 #2)
  [FAIL] flight_fidelity: aircraft position differs from the telemetry by 50.000 m at chase0 #1 t=0.525 s (recorded aircraft 135.826 N, 0.000 E, 3048.001 m; telemetry 85.826 N, 0.000 E, 3048.001 m at sample 5)
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (7/9 checks; FAILED: cross_view_consistency, flight_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt flight, flight_fidelity FAILED (also: cross_view_consistency); runs/demo_corrupt_flight/capture_manifest.json graded, report runs/demo_corrupt_flight/verify.json
```

#### verify --corrupt schedule: schedule fidelity must FAIL (an instant the spec does not schedule; every per-record check PASSES)

`python -m flightsim.verify runs/demo --corrupt schedule` -- exit 1, 0.56 s wall

```
corrupt schedule: manifest copied to runs/demo_corrupt_schedule; corrupted the instant at sample 59 (t=6.183 s -> sample 60, t=6.283 s) on chase0 #12, tower0 #12: sample_index, t_s, the aircraft state and the camera pose moved one telemetry sample later, the flight's own state and the spec's own solved pose at that sample copied in, so every per-record check still passes; only the schedule recomputed from the spec says the instant is wrong
  expected: [FAIL] schedule_fidelity, exit 1
run:         runs/demo_corrupt_schedule
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.283      60       865.621        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.283      60       900.000     -800.000      80.000  (626.5, 361.8)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  PASS      1.04e-12 m                     0.5 m                         24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       FAIL      2 of 48 instants differ        0 differ                      2 of 48 instants differ from the spec's schedule; worst chase0 #12 at sample 60 t=6.283 s where the spec schedules sample 59 t=6.183 s
  pose_fidelity           PASS      pos 0 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS      gap 4.1e-13 px                 1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] schedule_fidelity: 2 of 48 instants differ from the spec's schedule; worst chase0 #12 at sample 60 t=6.283 s where the spec schedules sample 59 t=6.183 s
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (8/9 checks; FAILED: schedule_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt schedule, schedule_fidelity FAILED; runs/demo_corrupt_schedule/capture_manifest.json graded, report runs/demo_corrupt_schedule/verify.json
```

#### verify --corrupt pose: pose fidelity must FAIL (one camera moved 5 m, its quaternion, Euler angles and aircraft untouched; cross-view fails beside it)

`python -m flightsim.verify runs/demo --corrupt pose` -- exit 1, 0.53 s wall

```
corrupt pose: manifest copied to runs/demo_corrupt_pose; corrupted tower0: every record's camera position_east_m += 5 m (24 frames); quaternion, Euler angles, lens and aircraft untouched, so the records agree with themselves and with the flight; only the pose recomputed from the spec says the camera was elsewhere
  expected: [FAIL] pose_fidelity, exit 1
run:         runs/demo_corrupt_pose
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 337.8)            22.2
       2     1.067      10         5.891        0.000    3060.001  (640.0, 339.1)            20.9
       3     1.608      15        91.530        0.000    3060.002  (640.0, 340.0)            20.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 340.2)            19.8
       5     2.683      25       268.383        0.001    3060.004  (640.0, 340.4)            19.6
       6     3.225      30       358.263        0.001    3060.004  (640.0, 340.4)            19.6
       7     3.767      35       448.213        0.001    3060.005  (640.0, 340.4)            19.6
       8     4.283      40       533.719        0.002    3060.006  (640.0, 340.2)            19.8
       9     4.783      45       616.554        0.002    3060.007  (640.0, 340.1)            19.9
      10     5.283      50       699.538        0.003    3060.007  (640.0, 340.1)            19.9
      11     5.783      55       782.571        0.003    3060.007  (640.0, 340.2)            19.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 340.2)            19.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 340.2)            19.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 340.2)            19.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 340.2)            19.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 340.3)            19.7
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 340.4)            19.6
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 340.4)            19.6
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 340.4)            19.6
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 340.4)            19.6
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 340.4)            19.6
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 340.4)            19.6
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 340.4)            19.6
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -795.000      80.000  (641.5, 358.8)             1.9
       1     0.525       5       900.000     -795.000      80.000  (633.5, 351.0)            11.1
       2     1.067      10       900.000     -795.000      80.000  (632.0, 350.3)            12.6
       3     1.608      15       900.000     -795.000      80.000  (631.2, 350.6)            12.9
       4     2.142      20       900.000     -795.000      80.000  (630.4, 351.1)            13.1
       5     2.683      25       900.000     -795.000      80.000  (629.7, 351.8)            13.2
       6     3.225      30       900.000     -795.000      80.000  (629.0, 352.6)            13.3
       7     3.767      35       900.000     -795.000      80.000  (628.2, 353.6)            13.4
       8     4.283      40       900.000     -795.000      80.000  (627.5, 354.6)            13.6
       9     4.783      45       900.000     -795.000      80.000  (626.9, 355.8)            13.8
      10     5.283      50       900.000     -795.000      80.000  (626.5, 357.1)            13.8
      11     5.783      55       900.000     -795.000      80.000  (626.3, 358.5)            13.8
      12     6.183      59       900.000     -795.000      80.000  (626.2, 359.6)            13.8
      13     6.683      64       900.000     -795.000      80.000  (626.2, 360.9)            13.8
      14     7.183      69       900.000     -795.000      80.000  (626.4, 362.2)            13.8
      15     7.683      74       900.000     -795.000      80.000  (626.7, 363.3)            13.7
      16     8.200      79       900.000     -795.000      80.000  (627.2, 364.3)            13.5
      17     8.742      84       900.000     -795.000      80.000  (627.8, 365.3)            13.3
      18     9.283      89       900.000     -795.000      80.000  (628.3, 366.0)            13.1
      19     9.825      94       900.000     -795.000      80.000  (628.9, 366.7)            13.0
      20    10.367      99       900.000     -795.000      80.000  (629.4, 367.2)            12.8
      21    10.908     104       900.000     -795.000      80.000  (629.9, 367.6)            12.7
      22    11.450     109       900.000     -795.000      80.000  (630.4, 367.9)            12.5
      23    11.992     114       900.000     -795.000      80.000  (630.8, 368.2)            12.3
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.58e-13 px                    0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  FAIL      2.4705 m                       0.5 m                         24 two-view instants; worst sample 0 t=0.008 s (chase0 #0 with tower0 #0); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           FAIL      pos 5 m, ang 0 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  camera position differs from the spec's track by 5.000 m at tower0 #0 t=0.008 s (recorded 900.000 N, -795.000 E, 80.000 m; the spec's track 900.000 N, -800.000 E, 80.000 m at sample 0)
  aim_fidelity            FAIL      gap 1.97 px                    1e-06 px, 1e-06 deg           the aircraft's pixel is 1.974 px from where the camera's promise puts it at tower0 #15 t=7.683 s (aircraft at (626.7, 363.3) px, promised (627.5, 365.1) px: aircraft-lagged, off-aim 13.7 px against a predicted 13.5)
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] cross_view_consistency: 24 two-view instants (rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft); worst triangulation error 2.4705 m (tol 0.5) at sample 0 t=0.008 s (chase0 #0 with tower0 #0)
  [FAIL] pose_fidelity: camera position differs from the spec's track by 5.000 m at tower0 #0 t=0.008 s (recorded 900.000 N, -795.000 E, 80.000 m; the spec's track 900.000 N, -800.000 E, 80.000 m at sample 0)
  [FAIL] aim_fidelity: the aircraft's pixel is 1.974 px from where the camera's promise puts it at tower0 #15 t=7.683 s (aircraft at (626.7, 363.3) px, promised (627.5, 365.1) px: aircraft-lagged, off-aim 13.7 px against a predicted 13.5)
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (6/9 checks; FAILED: cross_view_consistency, pose_fidelity, aim_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt pose, pose_fidelity FAILED (also: cross_view_consistency, aim_fidelity); runs/demo_corrupt_pose/capture_manifest.json graded, report runs/demo_corrupt_pose/verify.json
```

#### verify --corrupt lens: pose fidelity must FAIL (fx, fy and focal scaled 1.5x; geometry recovery still PASSES)

`python -m flightsim.verify runs/demo --corrupt lens` -- exit 1, 0.51 s wall

```
corrupt lens: manifest copied to runs/demo_corrupt_lens; corrupted chase0: every record's fx_px, fy_px and focal_length_mm x 1.5 (24 frames); the pose and the aircraft untouched, the aircraft still in frame, so geometry_recovery passes; only the lens recomputed from the spec's camera says otherwise
  expected: [FAIL] pose_fidelity, exit 1
run:         runs/demo_corrupt_lens
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1866.7 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (640.0, 360.0)             0.0
       1     0.525       5       -69.626        0.000    3060.000  (640.0, 326.6)            33.4
       2     1.067      10         5.891        0.000    3060.001  (640.0, 328.7)            31.3
       3     1.608      15        91.530        0.000    3060.002  (640.0, 330.0)            30.0
       4     2.142      20       178.732        0.000    3060.003  (640.0, 330.3)            29.7
       5     2.683      25       268.383        0.001    3060.004  (640.0, 330.6)            29.4
       6     3.225      30       358.263        0.001    3060.004  (640.0, 330.6)            29.4
       7     3.767      35       448.213        0.001    3060.005  (640.0, 330.6)            29.4
       8     4.283      40       533.719        0.002    3060.006  (640.0, 330.3)            29.7
       9     4.783      45       616.554        0.002    3060.007  (640.0, 330.2)            29.8
      10     5.283      50       699.538        0.003    3060.007  (640.0, 330.2)            29.8
      11     5.783      55       782.571        0.003    3060.007  (640.0, 330.2)            29.8
      12     6.183      59       849.010        0.004    3060.008  (640.0, 330.2)            29.8
      13     6.683      64       932.064        0.005    3060.008  (640.0, 330.2)            29.8
      14     7.183      69      1015.121        0.005    3060.009  (640.0, 330.2)            29.8
      15     7.683      74      1098.178        0.006    3060.009  (640.0, 330.2)            29.8
      16     8.200      79      1184.248        0.007    3060.009  (640.0, 330.5)            29.5
      17     8.742      84      1274.503        0.008    3060.009  (640.0, 330.7)            29.3
      18     9.283      89      1364.564        0.009    3060.009  (640.0, 330.7)            29.3
      19     9.825      94      1454.568        0.010    3060.010  (640.0, 330.6)            29.4
      20    10.367      99      1544.554        0.011    3060.010  (640.0, 330.6)            29.4
      21    10.908     104      1634.535        0.013    3060.010  (640.0, 330.6)            29.4
      22    11.450     109      1724.515        0.014    3060.010  (640.0, 330.6)            29.4
      23    11.992     114      1814.494        0.015    3060.010  (640.0, 330.6)            29.4
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                             TOLERANCE                     WHERE
  manifest_version        PASS      version 1                            = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records           0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                           0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  FAIL      1.4487 m                             0.5 m                         24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24                  exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg            1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS      0 of 48 instants differ              0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           FAIL      pos 0 m, ang 0 deg, lens 622.222 px  1e-06 m, 1e-06 deg, 1e-06 px  lens differs from the spec's camera by 622.222 px (17.500 mm) at chase0 #0 t=0.008 s (recorded fx 1866.667, fy 1866.667 px, focal 52.500 mm; the spec's camera fx 1244.444, fy 1244.444 px, focal 35.000 mm)
  aim_fidelity            PASS      gap 4.1e-13 px                       1e-06 px, 1e-06 deg           48 records; chase0 aircraft-lagged: off-aim up to 33.4 px, predicted 33.4; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           AWAITING  -                                    -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] cross_view_consistency: 24 two-view instants (rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft); worst triangulation error 1.4487 m (tol 0.5) at sample 10 t=1.067 s (chase0 #2 with tower0 #2)
  [FAIL] pose_fidelity: lens differs from the spec's camera by 622.222 px (17.500 mm) at chase0 #0 t=0.008 s (recorded fx 1866.667, fy 1866.667 px, focal 52.500 mm; the spec's camera fx 1244.444, fy 1244.444 px, focal 35.000 mm)
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (7/9 checks; FAILED: cross_view_consistency, pose_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt lens, pose_fidelity FAILED (also: cross_view_consistency); runs/demo_corrupt_lens/capture_manifest.json graded, report runs/demo_corrupt_lens/verify.json
```

#### verify --corrupt aim: aim fidelity must FAIL (one camera yawed 1 deg, quaternion and Euler together; the aircraft's pixel is no longer where the promise puts it)

`python -m flightsim.verify runs/demo --corrupt aim` -- exit 1, 0.51 s wall

```
corrupt aim: manifest copied to runs/demo_corrupt_aim; corrupted chase0: every record yawed 1 deg with the quaternion and the Euler angles rotated together (24 frames); position, lens and aircraft untouched, the aircraft still in frame, so geometry_recovery passes; only the promise recomputed over the telemetry says the camera looks the wrong way
  expected: [FAIL] aim_fidelity, exit 1
run:         runs/demo_corrupt_aim
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0      -110.000        0.000    3060.000  (618.4, 360.0)            21.6
       1     0.525       5       -69.626        0.000    3060.000  (618.3, 337.8)            31.0
       2     1.067      10         5.891        0.000    3060.001  (618.3, 339.2)            30.1
       3     1.608      15        91.530        0.000    3060.002  (618.3, 340.0)            29.5
       4     2.142      20       178.732        0.000    3060.003  (618.3, 340.2)            29.3
       5     2.683      25       268.383        0.001    3060.004  (618.3, 340.4)            29.2
       6     3.225      30       358.263        0.001    3060.004  (618.3, 340.4)            29.2
       7     3.767      35       448.213        0.001    3060.005  (618.3, 340.4)            29.2
       8     4.283      40       533.719        0.002    3060.006  (618.3, 340.2)            29.3
       9     4.783      45       616.554        0.002    3060.007  (618.3, 340.2)            29.4
      10     5.283      50       699.538        0.003    3060.007  (618.3, 340.2)            29.4
      11     5.783      55       782.571        0.003    3060.007  (618.3, 340.2)            29.4
      12     6.183      59       849.010        0.004    3060.008  (618.3, 340.2)            29.4
      13     6.683      64       932.064        0.005    3060.008  (618.3, 340.2)            29.4
      14     7.183      69      1015.121        0.005    3060.009  (618.3, 340.2)            29.4
      15     7.683      74      1098.178        0.006    3060.009  (618.3, 340.2)            29.4
      16     8.200      79      1184.248        0.007    3060.009  (618.3, 340.4)            29.2
      17     8.742      84      1274.503        0.008    3060.009  (618.3, 340.5)            29.2
      18     9.283      89      1364.564        0.009    3060.009  (618.3, 340.4)            29.2
      19     9.825      94      1454.568        0.010    3060.010  (618.3, 340.4)            29.2
      20    10.367      99      1544.554        0.011    3060.010  (618.3, 340.4)            29.2
      21    10.908     104      1634.535        0.013    3060.010  (618.3, 340.4)            29.2
      22    11.450     109      1724.515        0.014    3060.010  (618.3, 340.4)            29.2
      23    11.992     114      1814.494        0.015    3060.010  (618.3, 340.4)            29.2
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
     idx       t_s  sample   cam north m   cam east m   cam alt m  aircraft px (u, v)  off-aim px
       0     0.008       0       900.000     -800.000      80.000  (640.0, 360.0)             0.0
       1     0.525       5       900.000     -800.000      80.000  (632.1, 352.2)            11.1
       2     1.067      10       900.000     -800.000      80.000  (630.6, 351.7)            12.5
       3     1.608      15       900.000     -800.000      80.000  (629.9, 352.1)            12.8
       4     2.142      20       900.000     -800.000      80.000  (629.2, 352.6)            13.0
       5     2.683      25       900.000     -800.000      80.000  (628.7, 353.4)            13.1
       6     3.225      30       900.000     -800.000      80.000  (628.1, 354.3)            13.2
       7     3.767      35       900.000     -800.000      80.000  (627.5, 355.4)            13.3
       8     4.283      40       900.000     -800.000      80.000  (626.9, 356.5)            13.5
       9     4.783      45       900.000     -800.000      80.000  (626.5, 357.7)            13.6
      10     5.283      50       900.000     -800.000      80.000  (626.4, 359.1)            13.7
      11     5.783      55       900.000     -800.000      80.000  (626.3, 360.4)            13.7
      12     6.183      59       900.000     -800.000      80.000  (626.4, 361.5)            13.7
      13     6.683      64       900.000     -800.000      80.000  (626.7, 362.8)            13.6
      14     7.183      69       900.000     -800.000      80.000  (627.0, 364.0)            13.6
      15     7.683      74       900.000     -800.000      80.000  (627.5, 365.1)            13.5
      16     8.200      79       900.000     -800.000      80.000  (628.2, 366.0)            13.3
      17     8.742      84       900.000     -800.000      80.000  (628.9, 366.8)            13.0
      18     9.283      89       900.000     -800.000      80.000  (629.5, 367.5)            12.9
      19     9.825      94       900.000     -800.000      80.000  (630.1, 368.1)            12.7
      20    10.367      99       900.000     -800.000      80.000  (630.8, 368.5)            12.6
      21    10.908     104       900.000     -800.000      80.000  (631.3, 368.8)            12.4
      22    11.450     109       900.000     -800.000      80.000  (631.9, 369.1)            12.2
      23    11.992     114       900.000     -800.000      80.000  (632.4, 369.2)            12.0
  CHECK                   STATUS    MEASURED                       TOLERANCE                     WHERE
  manifest_version        PASS      version 1                      = 1                           spec cef57d752362381d
  fields_finite           PASS      0 non-finite of 48 records     0 non-finite                  48 records, 6 fields each
  geometry_recovery       PASS      4.1e-13 px                     0.5 px                        worst tower0 #9 t=4.783 s
  cross_view_consistency  FAIL      1.7 m                          0.5 m                         24 two-view instants; worst sample 114 t=11.992 s (chase0 #23 with tower0 #23); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS      48 frames = 24 + 24            exactly 48                    chase0 24/24, tower0 24/24
  flight_fidelity         PASS      t 0 s, pos 0 m, att 0 deg      1e-09 s, 1e-06 m, 1e-06 deg   48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS      0 of 48 instants differ        0 differ                      chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           FAIL      pos 0 m, ang 1 deg, lens 0 px  1e-06 m, 1e-06 deg, 1e-06 px  camera orientation differs from the spec's track by 1.0000 deg at chase0 #0 t=0.008 s (recorded yaw 1.0000, pitch -6.2258, roll 0.0000 deg; the spec's track 0.0000, -6.2258, 0.0000)
  aim_fidelity            FAIL      gap 21.7 px                    1e-06 px, 1e-06 deg           the aircraft's pixel is 21.675 px from where the camera's promise puts it at chase0 #14 t=7.183 s (aircraft at (618.3, 340.2) px, promised (640.0, 340.2) px: aircraft-lagged, off-aim 29.4 px against a predicted 19.8)
  engine_parity           AWAITING  -                              -                             awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
  detail:
  [FAIL] cross_view_consistency: 24 two-view instants (rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft); worst triangulation error 1.7000 m (tol 0.5) at sample 114 t=11.992 s (chase0 #23 with tower0 #23)
  [FAIL] pose_fidelity: camera orientation differs from the spec's track by 1.0000 deg at chase0 #0 t=0.008 s (recorded yaw 1.0000, pitch -6.2258, roll 0.0000 deg; the spec's track 0.0000, -6.2258, 0.0000); quaternion differs from the spec's track by 0.008719 at chase0 #16 t=8.200 s
  [FAIL] aim_fidelity: the aircraft's pixel is 21.675 px from where the camera's promise puts it at chase0 #14 t=7.183 s (aircraft at (618.3, 340.2) px, promised (640.0, 340.2) px: aircraft-lagged, off-aim 29.4 px against a predicted 19.8)
  [AWAITING] engine_parity: awaiting engine frames: no render.json for camera chase0, tower0 (the engine pass has not run on this machine; choose 'Render frames and clip' or --render frames where the engine exists)
verification FAILED (6/9 checks; FAILED: cross_view_consistency, pose_fidelity, aim_fidelity; 1 awaiting engine frames: engine_parity)
FAILED verification: as expected for --corrupt aim, aim_fidelity FAILED (also: cross_view_consistency, pose_fidelity); runs/demo_corrupt_aim/capture_manifest.json graded, report runs/demo_corrupt_aim/verify.json
```

<!-- examples_expected: end -->

Every mode runs that verifier on the manifest it just wrote and prints
the table BEFORE its final line (clip mode too, before its engine pass;
frames mode prints the complete table after its passes, when engine
parity has frames to grade), writes it as `verify.json` beside the
manifest (the same JSON the webapp serves, so `flightsim.verify`'s
output and the run's own record agree without re-running), records the
render choice and the JSBSim log in `run.json` (`render`: the word, the
page's label, and the engine's availability and reason on this machine
-- the CLI's copy of the webapp's `provenance.json` `render`;
`jsbsim_log`), and a manifest that fails its own verification fails
the run by name (`FAILED capture.verification:`, exit 1 -- the same
code `flightsim.verify` gives the same manifest). The headless tree is
`capture_manifest.json`, `telemetry.json`, `scenario.yaml`,
`run.json`, `verify.json`, `jsbsim.log`, `previews/<camera_id>/
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

The committed examples, each under a minute (times above):

* `examples/cameras_multi.yaml` -- a chase view and the tower, 24
  images each on the shared clock: cross-view consistency EXERCISED
  (24 two-view instants);
* `examples/cameras_multi_cockpit.yaml` -- the SAME flight (same
  simulation digest `7c9e52e245405487`, same output digest) with one
  cockpit camera, 24 images: the temporal-alignment pair, `verify
  runs/demo_b --against runs/demo` PASS with "24 instants in both
  runs; worst gap 0 s";
* `examples/cameras_waypoint.yaml` -- waypoint capture each 400 m of
  flown track (open loop; add `--terrain <bake>` over a real raster);
  one camera, so cross-view consistency is SKIPPED by name;
* `examples/cameras_refusal.yaml` -- a camera stated 600 m under the
  terrain datum; `REFUSED [camera.terrain_clearance]`, exit 2, the
  run directory holding `jsbsim.log` only. The refusal opens with the
  header printed from the SPEC ALONE (round 3: `run`, the spec and
  simulation digests with `output -` because nothing was flown, the
  scene and CRS, the flight, one line per camera with fx computed from
  the camera's focal length, sensor width and resolution and the
  captures column from the stated count or, when the flight decides
  it, the trigger -- "every 1 s, interval"), then the violation by
  name, the JSBSim line and the verdict; `--json` carries the same
  `header` block on the refusal path. Every refusal after the spec is
  read prints it (validation, the scene checks, the preview scale, the
  frames host-parity refusal, a schedule the telemetry cannot honour,
  a solved track that violates the scene); a spec that does not parse
  has no header to print.

### Watching each check fail on purpose

`flightsim.verify <run> --corrupt
{quaternion|aircraft|time|count|clock|flight|schedule|pose|lens|aim}`
copies the manifest (with `telemetry.json` and `scenario.yaml`) to a
SIBLING directory, `<run>_corrupt_<kind>/` (or `--corrupt-dir DIR`; a
copy inside the run is refused as USAGE), applies ONE named edit
(stated on the first line of the output), grades the copy with the
same verifier and must exit 1 with the named check FAILED -- the ten
blocks above
are the actual runs, and the verdict line names the copy's manifest
and report. The run directory itself stays exactly what capture wrote
(the CLI test lists it before and after every corruption), so nothing
that zips, lists or serves a run can pick a corrupted manifest up. Measured here: a 0.05 shift of one
quaternion component (the Euler angles untouched) is a 124.7076 px
quaternion-vs-Euler gap at `chase0 #3 t=1.608 s` (tol 0.5 px); a 5 m
shift of the tower's recorded aircraft is a 5.1845 m worst
triangulation error (tol 0.5 m) at sample 0; one instant moved by one
fixed step (0.008333 s) is "25 instants in demo_corrupt_time vs 24 in
demo; only in demo_corrupt_time: t=1.616667 s" (tol 1e-09 s); one
dropped record
is "47 frames = 23 + 24" against "exactly 48", `chase0 23/24` (missing
index 23).

**The verifier reads the flight, not only the manifest (round 2).** In
round 1 every check graded records against each other: a manifest with
EVERY record's aircraft moved 50 m north in both cameras verified 5/5
(the two views agreed with each other), every `t_s` shifted 0.5 s with
`sample_index` untouched verified 5/5, and `corrupt_time/` verified 5/5
when graded alone -- `telemetry.json` sat beside the manifest and was
never opened. Two checks now tie the manifest to the flight and to the
spec, with no sibling run:

* `flight_fidelity` -- `telemetry.json` beside the manifest must digest
  to the manifest's `output_digest` (the runner's hash, reimplemented
  in the verifier), and every record's `t_s` must be the telemetry's
  own `t` at its `sample_index`, its aircraft altitude and attitude the
  telemetry's at that sample, and its north/east the telemetry's
  lat/lon projected through the manifest's own frame block with pyproj
  (the verifier's projection, never the pose solver's). Tolerances are
  representation slack (1e-9 s, 1e-6 m, 1e-6 deg): the manifest copies
  these numbers, so any difference is a different flight.
* `schedule_fidelity` -- the capture schedule recomputed from
  `scenario.yaml`'s cameras over `telemetry.json`
  (`core/capture/schedule.py`, the spec's own trigger words) must
  match the manifest's instants sample for sample, per camera.

Measured on the three new corruptions (blocks above): `--corrupt clock`
(every instant +0.5 s) is `flight_fidelity FAIL, t 0.5 s, pos 0 m, att
0 deg` at chase0 #1 t=1.025 s against telemetry t=0.525000 s at sample
5, and `schedule_fidelity FAIL, 48 of 48 instants differ`, while
geometry, cross-view and count all still PASS; `--corrupt flight`
(aircraft north +50 m in every view) is `flight_fidelity FAIL, pos 50
m` -- in round 2 with `cross_view_consistency PASS 8.38e-13 m`, the
two views agreeing with each other and only the telemetry telling;
since round 3 the cross-view rays start at the recomputed poses and
are graded against the telemetry's aircraft, so that row reads `FAIL
50.0 m` beside it (graded from the records alone it still passes, and
says so); `--corrupt schedule`
(the shared instant at sample 59 moved to sample 60 on both cameras
with the flight's state AND the spec's solved pose at sample 60 copied
in) leaves EVERY
per-record check PASS and fails only `schedule_fidelity`, "2 of 48
instants differ; worst chase0 #12 at sample 60 t=6.283 s where the
spec schedules sample 59 t=6.183 s". `--corrupt time` now fails three
checks (flight, schedule and, against the original, temporal
alignment), and `corrupt_time/` graded alone is exit 1. When
`telemetry.json` or `scenario.yaml` is not beside the manifest the
checks that read them are SKIPPED by name, counted in neither passed
nor ran -- a manifest alone is graded only for its internal
consistency, and the summary says so.

**The pose is graded against the spec (round 3).** The judge's
demonstration against round 2: every CONSISTENT corruption of the
recorded camera verified 7/7 -- both cameras moved 30 m east, the
tower moved 5 m north, both cameras yawed 3 deg with the quaternion
and the Euler angles rotated together, the tower yawed 10 deg, fx/fy
and the focal length scaled 1.5x, the two camera ids swapped -- because
no check recomputed a pose and the manifest's per-camera
`pose_track_digest` was written and never read. Two things changed:

* `pose_fidelity` -- the pose track is solved AGAIN from
  `scenario.yaml`'s cameras over `telemetry.json` in the manifest's
  own frame block (`core/capture/verify.py::recompute_pose_tracks`;
  measured 0.0096 s for both cameras of cameras_multi, digests
  bit-identical to the manifest's), and every record's position,
  quaternion, yaw/pitch/roll, focal length, fx/fy, principal point,
  width/height, sensor and near/far are compared with the recomputed
  track at the record's sample (tolerances 1e-6 m, 1e-6 deg, 1e-9 in
  the quaternion, 1e-6 px, 1e-9 mm: representation slack, the manifest
  copies these numbers), and every camera block's `pose_track_digest`
  with the recomputed track's digest, verbatim. SKIPPED by name
  without the two files, never passed. All six of the judge's cases
  FAIL it on this machine (`tests/test_camera_verify.py::
  test_pose_fidelity_catches_the_judges_seven_pose_corruptions`): the
  30 m as `pos 30 m`, the 5 m as `pos 5 m`, the yaws as `ang 3 deg` /
  `ang 10 deg` with the quaternion gap beside them, the lens as `lens
  622.222 px (17.500 mm)`, the swap as `pos 3246.61 m, ang 138.366
  deg`; an edited digest and a record whose `width_px` is 1920 fail
  by name with the recomputed value printed.
* `cross_view_consistency` is no longer circular in the pose. Round
  2 cast each camera's ray from its OWN record's pose through that
  record's own projection of its own aircraft, so the ray passed
  through the aircraft by construction and the check reduced to "the
  two records agree on the aircraft". The ray now starts at the pose
  recomputed from the spec (with its lens) and goes through the
  record's own label pixel; the two rays must meet at one point, and
  that point must be the telemetry's aircraft at that sample (pyproj,
  as flight_fidelity projects it) and each record's own. An honest run
  gives the same 1.04e-12 m as before; the tower moved 5 m north gives
  5.1863 m, yawed 10 deg 185.2 m, both cameras yawed 3 deg 55.9 m, the
  lens scaled 1.5x 17.0 m, a camera moved 5 m ALONG its own axis
  0.597 m (the one geometry a single-point triangulation barely sees;
  pose_fidelity catches it at 5 m). Without `scenario.yaml` and
  `telemetry.json` the rays come from the records themselves and the
  WHERE column says exactly what that proves: "the two records agree
  on the aircraft; the poses are not tested here".

Two new corruptions (blocks above): `--corrupt pose` moves the tower's
every record 5 m east with its quaternion, Euler angles, lens and
aircraft untouched -- `pose_fidelity FAIL, pos 5 m` at "tower0 #0
t=0.008 s (recorded 900.000 N, -795.000 E, 80.000 m; the spec's track
900.000 N, -800.000 E, 80.000 m at sample 0)" and
`cross_view_consistency FAIL 2.4705 m`, while geometry, flight and
schedule all PASS; `--corrupt lens` scales the chase camera's fx, fy
and focal length 1.5x -- `pose_fidelity FAIL, lens 622.222 px (17.500
mm)` ("recorded fx 1866.667, fy 1866.667 px, focal 52.500 mm; the
spec's camera fx 1244.444, fy 1244.444 px, focal 35.000 mm"), with
`geometry_recovery PASS` because the quaternion still agrees with the
Euler angles and the aircraft is still in frame. On the single-camera
waypoint run both kinds fail `pose_fidelity` alone (cross-view
SKIPPED). `--corrupt quaternion` is now seen from three sides
(geometry recovery 124.7 px, cross-view 18.1 m through the twisted
label, pose fidelity's quaternion gap 0.05). The recomputation shares
the producer's pose solver (`core/capture/poses.py`), exactly as
schedule fidelity shares the scheduler: a bug in the solver itself is
caught by the solver's own tests (bit-identical digests, the preset
rules) and, on rendered frames, by engine parity -- not by this check;
what this check proves is that the manifest's poses ARE what the
committed spec commands over the recorded flight.

**The aim promise is graded (round 3).** The header prints "aim
aircraft (lag 0.25 s: the pixel trails the aircraft)" and the schedule
table an `off-aim px` column, but no check bounded that number: a
chase record 300 px off its aim verified. `aim_fidelity` now puts the
telemetry's aircraft (pyproj, the verifier's own projection) through
each record's own pose and lens and compares that pixel with the pixel
the preset's promise predicts, computed in the verifier without the
solver: for chase, wingman, tower and ground the first-order lag of
the aircraft track (time constant `AIM_LAG_S` = 0.25 s over the
recorded clock, starting on the aircraft) aimed from the record's
position with roll 0; for an explicit camera the aircraft itself (the
image centre); for a cockpit the cg pixel the spec's lens offsets put
along the body axis, with the record's axes compared to the
telemetry's roll/pitch/heading directly. Tolerance 1e-6 px (and 1e-6
deg on the cockpit axes): representation slack -- measured on the
committed runs the worst gap is 4.1e-13 px (cameras_multi), 4.53e-11
px (the cockpit pair; axes 0 deg) and 7.96e-13 px (the waypoint run),
and a camera turned 0.001 deg is already 0.022 px and FAILS. The row's
WHERE states the graded column per camera ("chase0 aircraft-lagged:
off-aim up to 22.2 px, predicted 22.2; tower0 ... 13.7, predicted
13.7"; the shoulder cockpit "off-aim up to 347.7 px, predicted
347.7"); a point- or bearing-aimed camera promises nothing and is
named "not graded"; the check is SKIPPED by name without
`telemetry.json`. `--corrupt aim` (block above) yaws the chase
camera's every record 1 deg with the quaternion and Euler angles
rotated TOGETHER, so `geometry_recovery` passes and the aircraft stays
in frame: `aim_fidelity FAIL, gap 21.7 px` -- "the aircraft's pixel is
21.675 px from where the camera's promise puts it at chase0 #14
t=7.183 s (aircraft at (618.3, 340.2) px, promised (640.0, 340.2) px:
aircraft-lagged, off-aim 21.7 px against a predicted 0.0)" -- with
`pose_fidelity` (ang 1 deg) and `cross_view_consistency` beside it.
`--corrupt pose` fails it too (1.97 px: the promise is computed from
where the record says the camera stands, and the record's orientation
was solved from where it really stood); `--corrupt lens` does not (the
measured and the promised pixel both go through the record's lens),
which is `pose_fidelity`'s catch. The check takes 0.065 s on
cameras_multi, the pyproj transformer included.

The corruption that cannot fail (`--corrupt aircraft` on a
single-camera run, where the check is SKIPPED) is refused as USAGE,
exit 3, rather than reported as caught. The same failures are unit
tests over corrupted manifests (`tests/test_camera_verify.py`) and
mutation guards (`scripts/mutation_check.sh`, the "commands round 1",
"commands round 2" and "commands round 3" sections among them: 24
round-3 guards -- the pose comparisons, the digest, the record
fields, the non-circular cross-view rays and their target, the aim
comparison, the lag filter, the cockpit axes, the three new
corruptions, the refusal header, the planning sink, the per-thread
slot -- each verified firing by the subset runner as it was added).

**The whole guard set, run to completion (2026-09-05).**
`./scripts/mutation_check.sh` at the head of this round's commits,
03:31 to 06:24 UTC on this Linux x86_64 machine: 311 guards, baseline
suite green, 305 ok, 0 WEAK, 6 SKIP ("could not apply mutation": a
target string the tree had moved away from -- four moved by this
round's own edits, the refusal header before the host-parity and
preview-scale refusals, the planning sink around `/capture`'s
preparation and the spec read once in `verify_run`; two older, the
drawn-aircraft budget variable renamed in the per-run-budget round and
the page's render=none branch reshaped by the preview-scale round),
restored suite green, 10378 s wall (2 h 53 min; the commands rounds'
guards each run `tests/test_camera_cli.py`, 85 s, which is most of
it). The six were repointed to the tree as it is and re-run through
the subset runner: 6 ok -- the render=none guard now degrades the
page's choice to the engine flow (`render = "clip"`) rather than
disabling one of the two branches that honour it, because `/run`'s
handler and `RunManager.start()` both route none to the headless
capture and removing either alone leaves the other. So the set
stands at 311 guards, every one load-bearing on this tree.

## Geometry preview (package I, done properly 2026-09-04; rounds 2 and 3 the same day)

`core/capture/preview.py` draws one PNG per scheduled frame with numpy
and Pillow only (matplotlib is not a dependency), every element
projected through the frame's OWN recorded pose and intrinsics by the
verifier's independent `project_point`, so the picture is an eyeball
check on the manifest: a wrong record would draw in the wrong place.
What a reader sees, and the field each element comes from:

| element | drawn as | source |
|---|---|---|
| terrain (terrain scenes) | a wireframe of the raster sampled every `terrain_stride_px` raster pixels (the smallest multiple of 4 giving at most 48 samples per axis: `control_ridge` 1024 px at 30 m is stride 24, 720 m, 43 x 43), each sample joined to its row and column neighbour, PLUS a fine lattice at a quarter of that stride (180 m) within 10 coarse steps (7.2 km) of the camera's ground point, so the near ground reads at the scale the aircraft is drawn; clipped at the near plane and to the image; shaded by camera-space depth: 240 at the frame's subject range (camera to aircraft) falling on a log scale to 32 at `far_m`; drawn far to near (painter's order) and HIDDEN behind nearer ground by a per-column skyline (`skyline_cull`: walking the segments near to far, each image column keeps the highest point drawn so far and a farther sample below it is behind a ridge) | the heightfield (name, size, pixel size: `Heightfield.metadata`), `near_m`, `far_m`, the aircraft state |
| ground grid (flat scenes) | a fine lattice (step = the nice number at or above height/4) and a coarse one (10x that step) on the plane at the spec's terrain elevation, origin snapped to the step, extent = min(`far_m`, fy x height / 2) so it reaches the horizon or the far plane | `position_*_m`, `fy_px`, `far_m`, the spec's terrain elevation |
| distance rings (every scene) | rings at 500 m, 1, 2, 5, 10, 20 km around the camera's EXACT ground point (never the snapped lattice origin: a ring labelled "10 km" is 10 km from the camera), labelled; in terrain scenes DRAPED on the raster (every ring point at the raster's elevation) and hidden behind ridges with the wireframe | `position_*_m`; the raster |
| north arrow (every scene) | a world-space arrow on the ground pointing north, its world length set so its PROJECTION spans 60 px (capped at 0.3 x the base's depth when north is foreshortened to nothing), based where the ray 90 px below the boresight meets the ground (plane, or raster marched and bisected) so it sits clear of the aircraft an aimed camera centres; its "N" label beside the arrow HEAD (right or left of the tip) | the pose, the ground |
| labels (round 3) | "boresight", "N" and the ring distances are REQUESTED with their anchor pixel while the geometry is drawn and PLACED once the header band, legend, compass and FOV text are known: each tries right, left, above and below its anchor (4 px off), then each side shifted outward by whole line heights (up to 6), first clear of every placed label by 20 px, then by 3 px (touching allowed, intersecting not), always clear of the reserved zones; an anchor INSIDE a zone (a ring under the header band) is offered the rows just below and above that zone; a label whose box ends farther than its gap plus one line height from its anchor gets a leader line from the anchor. Ring labels sit 25 deg round the ring from the camera's forward azimuth, or a quarter of the horizontal FOV if that is less (13.6 deg for the 35 mm lens), at least 80 px from the frame's sides -- off the column the arrow and the boresight share; on terrain, on the ring's VISIBLE piece nearest that point. `info["labels"]` reports every placement (anchor, box, side, shift, distance, leader, collided) | the placed geometry |
| compass rose (every scene) | image-space, bottom-right, 40 px: the N/E/S/W spokes with north at screen angle -yaw (clockwise from up; a camera yawed 90 east has north to its left) and the aircraft's heading as a second needle at heading - yaw, both numbered ("cam yaw 231.3", "hdg 0.0") | `yaw_deg`, `aircraft.heading_deg` |
| horizon | the level directions at infinity projected: `v = cy + fy tan(pitch)` for a level-rolled camera (a camera pitched down sees it ABOVE centre), tilted by roll. In terrain scenes it takes part in the SKYLINE (round 3): solid only in the columns where the drawn ground's top (the skyline from `skyline_cull`) lies below it, dashed (4 on, 8 off) in a dimmer colour where a ridge rises above the level horizon, so the level reference stays readable without being painted through a mountain; `info["horizon_visible_px"]` / `horizon_hidden_px` count the columns | `quaternion_wxyz`, intrinsics; the skyline |
| aircraft | a three-axis body: nose-tail along the recorded heading and pitch, wing tips at +/- span/2 with the recorded roll, a fin up from the centre; the length x span x height box; a heading tick beyond the nose | `aircraft.*` per frame; `aircraft_metrics` (below) |
| flown track | the run's TELEMETRY (`telemetry_track`: the recorder's samples in the scene frame, decimated by the integer stride that brings the rate to at or below 10 Hz, never interpolated; the rate MEASURED as the recorder's median step, 9.23 Hz for this recorder's 13-step spacing), past solid and future dim split at the frame's `t_s`, with this camera's scheduled instants as dots on the line; without telemetry (a synthetic manifest) the manifest's scheduled instants, and the header says which | `telemetry.json` columns `t`, `lat_deg`, `lon_deg`, `altitude_m`; the frame records |
| camera | a boresight cross at `principal_point_px` with the FOV `2 atan(sensor / 2 focal)` printed at the edges | `principal_point_px`, focal, sensor |
| header | camera id, "frame index 5 (6 of 24)" (the manifest's 0-based index a verifier greps for AND the human count), t, position, look yaw/pitch/roll, focal and fx, resolution, FOV; the aircraft's position, attitude, the aircraft-to-camera bearing and range; the body's span, length (with its caveat, below) and fin with their sources; the ground ("terrain control_ridge 1024x1024 @ 30 m, wireframe 43x43 (720 m) + 180 m within 7.2 km of the camera", or the flat lattice's steps and extent) with WHAT OF IT IS IN THE PICTURE (round 3): "(out of frame)" when no ground segment survived, "(none in frame)" for the rings, "(124 of 1314 coarse + 0 of 0 fine in view, 1190 hidden behind ridges)" on terrain, and the north arrow's state ("north arrow: drawn (45 px, 5892 m)" or "north arrow: ground out of frame"); the track's source. Font and line height derive from the image height (15 px at 720, 8 at 360, 22 at 1080) and a line wider than the image is wrapped at its field separators, continuation lines indented | the record; the camera block; the heightfield; the picture's own counts; the telemetry |

**The airframe metrics are read once from the FDM, never a constant**:
`core.scenario.runner.aircraft_metrics(fdm)` reads `metrics/bw-ft`
(span; the same property the span-station contact check uses) and
`sqrt(metrics/Sv-sqft)` (the vertical tail area's square side: the
FDM's only vertical extent). JSBSim states no nose-to-tail length, so
the longitudinal extent is the LARGER of two distances between stations
the FDM does state, each a lower bound on the fuselage: the extent of
the stated structural stations (`metrics/eyepoint-x-in`,
`metrics/visualrefpoint-x-in`, `metrics/aero-rp-x-in`, `inertia/cg-x-in`
and the tail arm `metrics/aero-rp-x-in` + 12 x `metrics/lh-ft`), and
the wing-to-tail arm plus one mean chord (`metrics/lh-ft` +
`metrics/cbarw-ft`). Measured: B747 eyepoint 308 in to tail arm 2656 in
= 59.6 m (arm + chord 40.8 m; the real fuselage is 70.7 m), c172p arm +
chord 6.3 m (stations 4.9 m; real 8.3 m). The block carries
`length_label` ("eyepoint to tail arm" / "arm + chord"),
`length_caveat` ("no fuselage length in JSBSim"), both candidates
(`length_candidates_m`) and a source string naming every station in
inches; the picture's body line reads "length >= 59.6 m (eyepoint to
tail arm; no fuselage length in JSBSim)" so a reader of the PNG alone
sees the caveat. The run manifest and the capture manifest carry the
block as `aircraft_metrics` (B747: span 64.47 m, length 59.64 m,
height 8.78 m). A manifest without it (a synthetic one) gets a fixed
cross and a header line "aircraft_metrics absent: body unscaled" --
never a silent guess.

**Resolution.** Full output resolution by default (the record's
`width_px` x `height_px`); `--preview-scale N` on the CLI and the
page's "preview scale 1/N" field draw at 1/N, the header and the CLI
line say so only when N is not 1. N must be a positive integer that
divides BOTH the width and the height exactly: anything else is
refused by name (`preview.scale`) BEFORE any flight -- the CLI checks
the spec's cameras (or the documented defaults) before `run_spec`
("REFUSED -- preview.scale: 3 does not divide 1280x720 exactly
(426.67x240); the preview draws at 1/N of the record's resolution and
never floors a size (camera chase0)", exit 2, no run directory) and
the page's `/run` and `/capture` answer 409 with constraint
`preview.scale` and no run id; `draw_preview` itself refuses the same
way. Round 2 floored 1280 // 3 to 426 with the intrinsics divided by
exactly 3 (the CLI printed "426x240, 1/3 scale": a silent
approximation with the principal point at 213.33 in a 426-px image);
that is gone. 4 and 5 draw (320x180, 256x144).

**Measured render time** (this machine, Linux, 4 cores, 2026-09-04,
round 3): 0.077 s/frame for the 48 frames of `examples/cameras_multi.yaml`
at 1280x720 (flat scene: lattice, rings, arrow, compass, telemetry
track, body, labels, header; `run.json` `previews.s_per_frame`
0.0770); 0.084 s/frame for the 5 frames of `examples/cameras_waypoint.yaml`
(280-point telemetry track); 0.090 s/frame for the 48 frames of the
`control_ridge` variant of cameras_multi with `--terrain` (coarse +
fine lattice, draped rings, skyline cull, the horizon against it).
The tests measure the same paths on synthetic scenes: the flat 48-
frame scene 0.0633 s/frame (0.0713 with the contact sheets: a tile
costs 0.0098 s), 24 terrain frames over a 97x97 raster with 400 m
ridges 0.0915 s/frame (0.1072 with the sheet; 433 coarse, 586 fine,
358 hidden per frame), 12 overlays over honest 1280x720 frames
0.1615 s/frame. The budget is 0.5 s/frame
(`RENDER_BUDGET_S_PER_FRAME`), graded by
`tests/test_camera_preview.py::test_full_resolution_render_time_is_under_budget`
(flat) and `::test_terrain_and_overlay_render_time_is_under_budget`
(terrain and overlays, round 3), both printing their numbers; every
run prints its own ("0.077 s/frame") and `run.json` `previews`
records it with `track_source`.

**Overlays** (`overlays/<camera_id>/NNNN.png`): after an engine pass,
`render_overlays` draws the same geometry as a translucent layer over
every rendered PNG that exists (named by the same index) at the
frame's OWN size, whatever it is: a frame whose size differs from its
record is drawn through the record's intrinsics scaled per axis by
the actual ratio (fx and cx by width, fy and cy by height) and its
header says so ("frame 640x360 differs from the record's 1280x720:
intrinsics scaled to the frame, pixels not resampled"); the rendered
pixels are never resampled, and the verifier, not the overlay, grades
the mismatch. The header band is no darker than 96/255
(`OVERLAY_BAND_ALPHA`). Round 3: every piece of overlay text -- the
legend, the compass letters, "cam yaw" / "hdg", HFOV, VFOV, the header
lines and every label -- carries a 2 px black stroke at the layer's
alpha (`TEXT_STROKE_PX`) and the compass sits on a disc of the band's
alpha (`COMPASS_BAND_PAD_PX` 16 beyond its ring), so the numbers read
over sky and ground; measured over a pure white frame at alpha 200,
all 15 text items and 5 labels have a dark pixel (55) and a light
pixel (188-255) in their box, the compass disc reads 159 (the band's
floor, no darker), and a pixel far from any geometry stays 255; the
plain preview draws no stroke. The CLI prints "overlays: 48
reprojected-geometry overlay(s) ... (0.0xx s/frame)" and records
`overlays {count, s_per_frame}` in `run.json`; the page lists
`capture/overlays/<camera_id>` with the note "reprojected geometry
over the rendered frame". Exercised here only against the honest
engine STUB (a blob at the labelled pixel) and synthetic frames;
"awaiting Windows verification" on real pixels, step 5c below.

**Contact sheets** (`contact_sheets/<camera_id>.png`, beside
`previews/`, never inside it -- `previews/` holds exactly one PNG per
drawn frame): every preview of the camera as a 320x180 tile DRAWN FOR
THE TILE from its frame record (round 3: `draw_preview` at the tile's
size in the thumbnail style -- the record's intrinsics scaled per
axis, nothing resampled, no text of any kind, the horizon, track,
body and box at 2 px), never the preview shrunk: round 2's
`Image.thumbnail()` of the 1280x720 preview smeared the one-pixel
lattice and track to nothing and the six-line header into a band
over the top 15% of every tile. Measured on cameras_multi chase0's
tile #5: geometry pixels brighter than the background by 70 are 6.47%
of the tile against 1.30% for the shrunk preview (the judge measured
0.51% on the round-2 sheet), the peak pixel 255 against 159; the tile
draws 0 text items where the full preview draws 20. Under each tile
"#5 (6/24)  t=2.683 s" (index and count); a title row with camera id,
preset, schedule basis, "N of M frames" and "tiles 320x180 drawn from
the records; previews 1280x720". `docs/images/contact_sheet_chase0.png`
is the chase0 sheet of the command above. Listed by the CLI and shown
whole on the page above the per-frame gallery.

**Reference image**: `docs/images/preview_chase0_frame5.png` is frame
index 5 of `chase0` from the command above (t=2.683 s, camera at N
+268.4, alt 3060 m, pitch -4.8 deg), round 3: the horizon at row 255.4
(= 360 + 1244 tan(-4.8 deg)), the 747's 64.5 m span drawn 455 px wide
at 176 m range (1244 x 64.5 / 176 = 456), the 59.6 m box around it,
the boresight cross with "boresight" beside it (box 658-716 x 354-366,
18 px from the cross, no leader), the 10 km ring at row 629 (= 360 +
1244 tan(atan(3060 / 10000) - 4.8 deg): 10 km from the camera, not
10.27 km from the snapped lattice origin) labelled at (939, 633) --
13.6 deg round the ring from the forward azimuth, 295 px right of the
arrow's column, 4 px from its anchor -- the 20 km ring labelled at
(942, 443), the telemetry track through the aircraft with the
scheduled dots, the north arrow 90 px below the boresight (45 px
long: its base is 5.9 km out on the 0.3 x depth cap, north being
foreshortened there) with "N" beside its head at (644, 397) 4 px
right of the tip (640, 405), the compass with N up (yaw 0) and the
heading needle on it, the coarse lattice dim in the distance, and a
six-line header (band 108 px) whose ground line ends "north arrow:
drawn (45 px, 5892 m)". Byte-identical to a fresh draw of the record
(the test probe compares the arrays).

**Label placement, measured** over every preview of the judge's three
runs (cameras_multi, cameras_waypoint, control_ridge with --terrain;
120 + 25 + 118 labels): round 2 had 1 overlapping pair with
"boresight" 136 px below its cross (cameras_waypoint survey #2, on top
of "5 km"), 119 px off in control_ridge chase0 #1, and "N" 60-80 px
below the arrow tip -- beneath its base -- in every chase frame, with
the ring labels on the arrow's shaft whenever the camera looked
north; round 3 has 0 overlapping pairs and 0 collided placements,
worst distances boresight 18 px, N 4 px, ring 22 px (with a leader).
Over the three example scenes rebuilt in-test on synthetic telemetry
(100 frames; the third over the committed `control_ridge` raster):
0 intersections, 0 collided, no label on the band or the compass;
the tower frames' ring and N labels, anchored inside the 108-125 px
band, sit just below it with leaders.

**The horizon behind ridges, measured**: with `two_ridge_heightfield`
and the camera at 100 m a kilometre south of the 300 m ridge (crest
at v=111, horizon row v=360), round 2 painted 157 of 160 sampled
horizon-row pixels in the horizon colour across the ridge face; round
3 paints 0 of 160. A half-ridge scene (the ridge on the east half
only) splits at u=557, where the west slope crosses the row (foot at
u=516/v=484, crest at u=640/v=111, interpolated 557): 557 columns
visible + 723 hidden = 1280; east of the boresight label 0 of 552
pixels are horizon-coloured and 230 (5/12: Pillow paints a line from
u to u+4 as 5 pixels) are dashes.

**Hidden counts, per kind**: `info["segments"]` counts, for the
coarse lattice, the fine lattice and the rings separately, the
segments in frame, those with at least one visible run (from
`skyline_cull`'s source array), those with none (hidden), with hidden
+ visible == in frame, and the visible runs drawn apart. On the judge's
scene: coarse 1314 in frame, 124 with a visible run, 1190 hidden, 134
runs; rings 66 in frame, 44 visible, 22 hidden. Round 2's single
"terrain_hidden" (1202 there; 238 on control_ridge chase0 #5 against
459 - 295 = 164) was len(all clipped) - len(all runs) across the
kinds, which nothing reconciles with.

**Tests** (`tests/test_camera_preview.py`, 42 tests on synthetic
records with known poses): the level camera's horizon row equals cy
within 1 px and a ground point ahead lands below it; pitch -10 deg
moves it by fy tan(pitch); the body centre equals `project_point` of
the aircraft within 1 px; the wing-tip separation equals fx x span /
range within 1 px and halves at twice the range; roll and heading move
the tips and nose as recorded; a segment behind the camera is not
drawn, even when its mirrored projection would land in frame; the
default size is the record's; the header carries the position, look
and focal strings and the exact "frame index 5 (6 of 24)"; the overlay
is the frame's size with the body at the reprojected pixel; one
contact sheet per camera with one thumbnail per frame; the render time
is under budget. Round 2 adds: two crossing segments given far-last
leave the near colour on the crossing pixel; a two-ridge heightfield
(near 300 m at 1 km, far 150 m at 2 km) hides the far crest where it
crosses the near face; a 200-point half-circle telemetry at 20 Hz is
decimated to 101 points at 10 Hz with the words "track: telemetry 20
Hz decimated to 10 Hz (101 points)", intermediate points lie on the
drawn track in the past colour before the frame's instant and the
future colour after, the chord midpoint is background, and the
recorder's median step sets the rate; the 10 km ring's forward point
projects at cy + fy tan(atan(3060/10000) - 4.8 deg) within 1 px; the
compass's N spoke sits at -yaw for yaw 0, 90 and 231.3; the north
arrow is 60 px on screen within 1 px in a flat and a terrain scene;
640x360 and 1920x1080 frames get overlays of their own size; the
terrain header names the raster; the fine lattice lies within its
radius and never on a coarse line; the body line carries the caveat;
the runner's B747 length is 59.644 m. Round 3 adds (10 tests): the
contact-sheet tile has the horizon on rows cy/4 and cy/4 + 1, the body
centre at the reprojected pixel over 4, grid, rings, arrow and track
present, no text pixel and no band inside any tile, the label under
it, and a fresh sheet byte-identical; a 400x225 record whose position
line measures 440 px wraps to 8 drawn lines from 6, every line within
w - 8, continuation lines indented, no bright pixel in the band's
rightmost 8 columns (a 480x270 record does NOT wrap: widest line 440
px against 472 of room); over the three example scenes no two label
boxes intersect, none collides, every label is within 24 px of its
anchor or has a leader, none lies on the band or the compass,
"boresight" is within 20 px of its cross, "N" is centred on the tip's
row right or left of it, ring anchors are more than 100 px off the
arrow's column; eight labels on one anchor all place with 0
intersections and leaders on the far ones, a label anchored inside
the band lands below it; the half-ridge horizon split at the
projected crossing, the flat scene whole, the full ridge entirely
hidden, the tile at a quarter; every overlay text item and label has
a dark and a light pixel over a white frame, the compass disc within
the band's alpha, a far pixel unchanged, the plain preview stroke-
free; 3 on 1280x720 refused by name everywhere with "(426.67x240)" in
the words, 5 draws 256x144, the camera check names the camera from
records and CameraSpec blocks (the CLI test's loop gains "3", the page
test 3 on /capture and /run); the tower camera's header reads "(out of
frame)", "(none in frame)" and "north arrow: ground out of frame", the
aimed camera's "north arrow: drawn (60 px, ...)"; the per-kind counts
reconcile with an independent recomputation and equal the numbers
above; the terrain and overlay render times are under budget. The
CLI and page tests assert the run's `track_source` equals the words
computed from the run's own telemetry.

**Mutation guards** (`scripts/mutation_check.sh`): the 15 round-1
guards ("the geometry preview"), the 21 round-2 guards ("preview
round 2") and the 18 round-3 guards ("preview round 3") each disable
one safeguard and require its test to fail; `--only <label regex>`
runs a named subset. Round 2's guard "header lines wider than the
image are wrapped" was WEAK (its only assertion held without wrapping
because no header line exceeded the 640x360 or 1920x1080 frames);
round 3's 400x225 test makes it fire. The whole preview set (56
guards: rounds 1-3, the airframe-metrics, overlay, page-scale and
frames-provenance guards) was run to completion in round 3 through
the subset runner (23:05-23:27 UTC, 2026-09-04): 53 ok, 0 WEAK, 3 SKIP
whose target strings round 3 had moved (the round-1 header guard, the
round-2 band-alpha and raster-name guards), repointed and re-run: ok.
The round-2 subset the previous session left unfinished therefore
stands at 21 ok, of which the wrap guard was WEAK until round 3's test.
Its output:

```
  ok    a frames run records its passes and its clip in provenance -- tests fail with the guard removed
  ok    the CLI records its passes and its clip beside the run's digests -- tests fail with the guard removed
  ok    the preview draws the horizon at the camera's pitch and roll -- tests fail with the guard removed
  ok    the aircraft body is scaled by the FDM's span at the frame's range -- tests fail with the guard removed
  ok    a segment behind the camera is never drawn -- tests fail with the guard removed
  ok    previews default to the record's full resolution -- tests fail with the guard removed
  ok    a preview scale that is not a positive integer refuses by name -- tests fail with the guard removed
  ok    the ground is depth-shaded, near bright and far dim -- tests fail with the guard removed
  SKIP  the header states position, look direction and focal length -- could not apply mutation
  ok    every camera gets a contact sheet of its previews -- tests fail with the guard removed
  ok    the preview render time is measured per frame and recorded -- tests fail with the guard removed
  ok    the run manifest carries the airframe metrics read from the FDM -- tests fail with the guard removed
  ok    the capture manifest carries the airframe metrics the body is scaled by -- tests fail with the guard removed
  ok    a frames run overlays the reprojected geometry on every rendered frame (CLI) -- tests fail with the guard removed
  ok    a frames run overlays the reprojected geometry on every rendered frame (page) -- tests fail with the guard removed
  ok    the page lists the overlays as their own artefact class -- tests fail with the guard removed
  ok    the page's preview scale is honoured or refused by name -- tests fail with the guard removed
  ok    preview round 2: segments are drawn far to near (painter's order) -- tests fail with the guard removed
  ok    preview round 2: ground behind a nearer ridge is hidden by the skyline -- tests fail with the guard removed
  ok    preview round 2: the flown track is the telemetry, not the schedule's chords -- tests fail with the guard removed
  ok    preview round 2: the telemetry rate is the recorder's median step -- tests fail with the guard removed
  ok    preview round 2: the past/future split is at the frame's instant -- tests fail with the guard removed
  ok    preview round 2: distance rings are centred on the camera's exact ground point -- tests fail with the guard removed
  ok    preview round 2: the compass puts north at minus the camera's yaw -- tests fail with the guard removed
  ok    preview round 2: the north arrow is drawn in every scene -- tests fail with the guard removed
  ok    preview round 2: the arrow's world length is set by its projected size -- tests fail with the guard removed
  ok    preview round 2: overlays scale the intrinsics per axis to the frame's own size -- tests fail with the guard removed
  SKIP  preview round 2: the overlay's header band darkens the frame by at most 96/255 -- could not apply mutation
  ok    preview round 2: header lines wider than the image are wrapped -- tests fail with the guard removed
  SKIP  preview round 2: the header names the raster, its resolution and the wireframe spacing -- could not apply mutation
  ok    preview round 2: the fine lattice densifies the ground near the camera -- tests fail with the guard removed
  ok    preview round 2: distance rings are draped on the raster in terrain scenes -- tests fail with the guard removed
  ok    preview round 2: the body length is the larger stated station extent, named -- tests fail with the guard removed
  ok    preview round 2: the body line carries the length caveat -- tests fail with the guard removed
  ok    preview round 2: the header numbers frames by index AND count -- tests fail with the guard removed
  ok    preview round 2: the contact sheet label carries index and count -- tests fail with the guard removed
  ok    preview round 2: the CLI passes the run's telemetry to the previews -- tests fail with the guard removed
  ok    preview round 2: the page passes the run's telemetry to the previews -- tests fail with the guard removed
  ok    preview round 3: contact-sheet tiles are drawn for the tile, without text -- tests fail with the guard removed
  ok    preview round 3: tile lines are drawn at THUMBNAIL_LINE_PX -- tests fail with the guard removed
  ok    preview round 3: a label placed far from its anchor gets a leader line -- tests fail with the guard removed
  ok    preview round 3: labels try right, left, above and below their anchor -- tests fail with the guard removed
  ok    preview round 3: labels keep clear of the header band, legend and compass -- tests fail with the guard removed
  ok    preview round 3: ring labels are anchored off the arrow's column -- tests fail with the guard removed
  ok    preview round 3: the horizon is hidden where the skyline rises above it -- tests fail with the guard removed
  ok    preview round 3: the hidden horizon is dashed in its own colour -- tests fail with the guard removed
  ok    preview round 3: overlay text carries a dark stroke -- tests fail with the guard removed
  ok    preview round 3: the overlay's compass sits on its own band -- tests fail with the guard removed
  ok    preview round 3: a scale that does not divide the resolution is refused by name -- tests fail with the guard removed
  ok    preview round 3: the CLI refuses a non-divisor preview scale before the flight -- tests fail with the guard removed
  ok    preview round 3: the page refuses a non-divisor preview scale before the run -- tests fail with the guard removed
  ok    preview round 3: the ground line says (out of frame) when no ground segment survived -- tests fail with the guard removed
  ok    preview round 3: the header states the north arrow's state -- tests fail with the guard removed
  ok    preview round 3: hidden counts are per kind and reconcile with the segments in frame -- tests fail with the guard removed
  ok    preview round 3: a label anchored inside a reserved zone is offered the rows beside it -- tests fail with the guard removed
  ok    preview round 3: the overlay render time is measured per frame and graded -- tests fail with the guard removed

SUBSET: 3 guard(s) NOT covered  (the three SKIPs: their target strings had moved in round 3; repointed and re-run alone:)

  ok    the header states position, look direction and focal length -- tests fail with the guard removed
  ok    preview round 2: the overlay's header band darkens the frame by at most 96/255 -- tests fail with the guard removed
  ok    preview round 2: the header names the raster, its resolution and the wireframe spacing -- tests fail with the guard removed

SUBSET: all guards load-bearing
```

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
.venv\Scripts\python -m flightsim.capture examples\cameras_multi.yaml --out runs\demo --render frames --brief
```

Expected output: the block below is what that command prints, line
for line, measured here in a child process that stubs EXACTLY these
six pieces (`scripts/examples_expected.py`'s `STUBBED` tuple, which
the freshness test checks against the child's own source, so a new
stub cannot go undisclosed): `flightsim.capture.run_render_pass` (the
commandlet's consume-poses pass, replaced by `tests.test_camera_cli.
honest_cli_engine`, which reads the card and writes the scheduled PNGs
and `render.json` the contract specifies), `flightsim.capture.
encode_scheduled_clip` (the by-product clip's ffmpeg concat call,
replaced by a placeholder writer: `clip.mp4` is the 3 bytes `mp4`),
`core.util.platform.find_ffmpeg` (a fake path; no ffmpeg on this
machine, none run), `core.util.platform.ue_available` and
`core.util.platform.ue_unavailable_reason` (the engine gate held
open), and `webapp.runs.refuse_placeholder_mesh` (disabled: the B747
mesh is not imported here). Everything else -- the flight, the card, the 15 model loads,
the schedule, the previews, the overlays, the verifier -- is the real
code. So the block's `clip:` line, and run.json's `clip_encoded true`
/ `clip_seconds 12.992`, are the playlist arithmetic (black lead-in,
24 instants, a 1 s hold) over a placeholder file, not an encode, until
section 5b's ffprobe measures the Windows file.
The Windows log must match it with three differences: paths print
with backslashes (`runs\demo\...`); the `engine_parity` row's MEASURED
cell, masked `x` here, carries the engine's own numbers; and the
`clip:` line reads as below only with ffmpeg on PATH (or at
`FLIGHTSIM_FFMPEG`, `C:\ffmpeg\bin\ffmpeg.exe` or `C:\Program
Files\ffmpeg\bin\ffmpeg.exe`) -- without it `flightsim/capture.py`
prints, in that line's place (measured here with the platform word
patched to windows):

```
  clip: not encoded (FfmpegMissingError: ffmpeg.missing: no ffmpeg found (checked FLIGHTSIM_FFMPEG, PATH, and the usual windows locations). Install it with: winget install ffmpeg   (or choco install ffmpeg) -- compiling and headless runs work without it; only video encoding needs it.); the frames stand on their own
```

and, with ffmpeg present but failing, `  clip: ffmpeg could not encode
the by-product clip; the frames stand on their own`; either way
run.json records `clip_encoded false` and the rest of the block, the
verdict included, is unchanged (the frames are the deliverable).
`--brief`
collapses each camera's schedule table to one line; without it the
full tables of the first Linux block print in the same place. The
step counts (1439 of 1440 steps per pass) are the schedule's own --
the last instant, 11.992 s, on the 120 Hz grid -- and section 3
requires the same of the engine's log, so a different count on
Windows is a finding to report, not a digit to fill in.

<!-- frames_expected: begin -->
Measured 2026-09-05 on Linux x86_64, Python 3.11.15 on the honest engine STUB by `scripts/examples_expected.py` (stdout verbatim, paths normalised to `runs/...` where Windows prints `runs\...`; wall times are this machine's). Stubbed in the child process, and nothing else: `flightsim.capture.run_render_pass` -- the commandlet's consume-poses pass replaced by `tests.test_camera_cli.honest_cli_engine`, a Python function that reads -scenario= and -camera-index= off the argv and writes the scheduled PNGs and render.json the contract specifies; `flightsim.capture.encode_scheduled_clip` -- the by-product clip's ffmpeg concat call replaced by a placeholder writer: `clip.mp4` is the 3 bytes `mp4`, never an encode; `core.util.platform.find_ffmpeg` -- a fake path (no ffmpeg on this machine, none run); `core.util.platform.ue_available` -- held open (True) so the engine branch is entered; `core.util.platform.ue_unavailable_reason` -- None, the same gate; `webapp.runs.refuse_placeholder_mesh` -- disabled (the B747 mesh is not imported here, so `aircraft.mesh` would refuse by name). The flight, card, manifest, schedule, previews, contact sheets, overlays and verifier are the real code. The `clip:` line, and run.json's `clip_encoded true` / `clip_seconds 12.992`, are the playlist arithmetic (black lead-in, 24 instants, a 1 s hold) over a placeholder file, not an encode: section 5b's ffprobe on the Windows machine is the measurement. The `engine_parity` row's MEASURED cell is masked `x`: those digits come from the Windows run and are written in here from its log. Everything else -- every other line, digest, count and check number -- the Windows log must print the same, or the difference is the finding. `tests/test_camera_cli.py::test_the_documents_windows_frames_block_matches_the_stub_run` regenerates this block and compares it as the Linux blocks are compared.

#### capture --render frames: two cameras, one flight (cameras_multi), on the honest engine STUB

`.venv\Scripts\python -m flightsim.capture examples\cameras_multi.yaml --out runs\demo --render frames --brief` -- exit 0, 15.24 s wall on the stub

```
spec cef57d752362381d valid; running headlessly...
run:         runs/demo
spec         cef57d752362381d   simulation 7c9e52e245405487   output 2c3eac9056d8257c
scene        flat (no raster)   crs EPSG:32631
flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t 0.008..11.992 s (115 samples, 0.108 s apart); span 64.5 m
cameras      2
  chase0  chase/offset  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  tower0  tower/scene  aim aircraft (lag 0.25 s: the pixel trails the aircraft)  1280x720  35.0 mm (fx 1244.4 px)  24 captures, interval
  card:     runs/demo/card.json (consume-poses; one commandlet pass per camera via -camera-index=N)
JSBSim output: runs/demo/jsbsim.log (15 model loads; nothing of JSBSim's on stdout)
scheduled 48 frames across 2 camera(s)
  chase0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
    0..23 spaced 0.400..0.542 s (sample-snapped, not uniform) from 0.008 s to 11.992 s (samples 0..114)
  tower0: 24 scheduled instant(s) (count 24 spread over [0.00833333, 11.9917] s, endpoints included)
    0..23 spaced 0.400..0.542 s (sample-snapped, not uniform) from 0.008 s to 11.992 s (samples 0..114)
  manifest: runs/demo/capture_manifest.json
  previews: 48 geometry preview(s) at 1280x720, 0.075 s/frame under runs/demo/previews (previews are not frames; track: telemetry 9.23077 Hz (115 points, no decimation))
  contact sheets: 2 (contact_sheets/<camera_id>.png, one per camera)
engine pass 1 of 2: camera 'chase0', 24 frames scheduled over the 12 s run (-camera-index=0)
  camera 'chase0': 24 of 24 scheduled frames rendered under runs/demo/frames/chase0 (engine stepped 11.992 s in 1439 steps)
engine pass 2 of 2: camera 'tower0', 24 frames scheduled over the 12 s run (-camera-index=1)
  camera 'tower0': 24 of 24 scheduled frames rendered under runs/demo/frames/tower0 (engine stepped 11.992 s in 1439 steps)
  overlays: 48 reprojected-geometry overlay(s) over the rendered frames under runs/demo/overlays (0.170 s/frame; the aircraft box, wireframe and horizon the manifest predicts, drawn on the engine's pixels)
  clip:     runs/demo/clip.mp4 (by-product of camera 'chase0', 24 frames at their scheduled instants; 12.992 s = black to t=0.008 s, the flight to t=11.992 s, a 1 s hold)
  CHECK                   STATUS  MEASURED                                          TOLERANCE                        WHERE
  manifest_version        PASS    version 1                                         = 1                              spec cef57d752362381d
  fields_finite           PASS    0 non-finite of 48 records                        0 non-finite                     48 records, 6 fields each
  geometry_recovery       PASS    4.1e-13 px                                        0.5 px                           worst tower0 #9 t=4.783 s
  cross_view_consistency  PASS    1.04e-12 m                                        0.5 m                            24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness         PASS    48 frames = 24 + 24                               exactly 48                       chase0 24/24, tower0 24/24
  flight_fidelity         PASS    t 0 s, pos 0 m, att 0 deg                         1e-09 s, 1e-06 m, 1e-06 deg      48 records against 115 samples; digest 2c3eac9056d8257c = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity       PASS    0 of 48 instants differ                           0 differ                         chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity           PASS    pos 0 m, ang 0 deg, lens 0 px                     1e-06 m, 1e-06 deg, 1e-06 px     48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity            PASS    gap 4.1e-13 px                                    1e-06 px, 1e-06 deg              48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity           PASS    pos x.xxx m, ang x.xxx deg, t x.xe+xx s, px x.xx  0.1 m, 0.1 deg, 1e-06 s, 3.0 px  48 of 48 frames verified across 2 camera(s)
verification PASSED (10/10 checks)
done: rendered 48 frames across 2 camera(s) (48 verified by engine parity) under runs/demo/frames
```

<!-- frames_expected: end -->

The `x` digits are the numbers this section exists to obtain; write
them in here from the log. The row's `detail` sentence in
`runs\demo\verify.json` (a PASS prints once, in the table; the prose
is in the file) carries them by name -- on the stub it reads "48
frames across 2 camera(s); worst position 0.000 m (tol 0.1); worst
angle 0.000 deg (tol 0.1); worst time 0.0e+00 s (tol 1e-06; every
instant on the 120 Hz grid, the engine stepped 0.008333 s); pose
applied at the scheduled instant to 0.0e+00 s; worst reprojection
0.00 px (tol 3.0); aircraft drawn within 0.00 m of the manifest's
aircraft (budget 2.08 m = 1.5 steps x 1.384 m/step at 166.0 m/s) and
0.0 px of its labelled pixel (tol 3.8 px at that frame's 3076 m); the
engine measured its aircraft within 0.0 px of the label and 0.00 px
of the manifest's projection model (tol 3.0); lowest label window
contrast 44.2 against background 30.0 (min 8)", every zero the stub's.
What each one tells:

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
placeholder rule refuses `aircraft.mesh` otherwise). The two lines
are pinned: `tests/test_camera_cli.py::
test_section_3s_commandlet_lines_are_render_commands_own` builds them
from `render_command` with this UE_ROOT and checkout and compares
token for token, so a flag added, renamed or reordered on either side
fails the suite:

```
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" C:\flightsim\ue\FlightSim.uproject -run=FlightSimBridge.FlightSimRender -scenario=C:\flightsim\runs\demo\card.json -frames=C:\flightsim\runs\demo\frames\chase0 -Visual -shot=showcase -camera-index=0 -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -unattended -nopause -nosplash -stdout -FullStdOutLogOutput -RenderOffScreen -AllowCommandletRendering -mesh=C:\flightsim\assets\generated\B747\mesh_manifest.json -telemetry=C:\flightsim\runs\demo\engine_telemetry.json
"C:\Program Files\Epic Games\UE_5.5\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" C:\flightsim\ue\FlightSim.uproject -run=FlightSimBridge.FlightSimRender -scenario=C:\flightsim\runs\demo\card.json -frames=C:\flightsim\runs\demo\frames\tower0 -Visual -shot=showcase -camera-index=1 -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -unattended -nopause -nosplash -stdout -FullStdOutLogOutput -RenderOffScreen -AllowCommandletRendering -mesh=C:\flightsim\assets\generated\B747\mesh_manifest.json
```

Each pass's editor log lands in `runs\demo\frames\<camera_id>\render.log`
and MUST contain, in this order (the `%d`/`%.3f` values are the
example's; `tests/test_camera_cli.py::
test_section_3s_render_log_lines_are_the_commandlets_own_format_strings`
turns each line back into its `%d`/`%.3f`/`%.6f`/`%s` skeleton and
requires it to be a `TEXT(...)` literal of
`FlightSimRenderCommandlet.cpp`, in the source's order, with the
example's numbers read from the section 2 block -- so a log word
changed in the C++ or here fails the suite, engine or no engine):

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
  clip.mp4                     the by-product: black to t=0.008 s, 24 frames at their instants to t=11.992 s, the last held 1 s: 12.992 s by the playlist arithmetic -- a placeholder here (3 bytes: the stub replaces the encoder); on Windows the encoded file, which section 5b measures, or absent without ffmpeg (step 2's alternative clip line; clip_encoded false)
  run.json                     spec_digest, output_digest, samples 115, render {choice "frames", label "Render frames and clip", engine_available true, engine_unavailable_reason null}, jsbsim_log, previews {count 48, scale 1, resolution [1280, 720], s_per_frame, track_source, contact_sheets {chase0, tower0}}, render_passes (per camera: camera_id, camera_index, scheduled 24, rendered 24, steps_taken 1439, stepped_s 11.992), clip_encoded true, clip_seconds 12.992 (the playlist arithmetic; true only because the stub's placeholder writer returned true -- on Windows, true only if ffmpeg encoded the file), overlays {count 48, s_per_frame} -- the keys as the stub run wrote them (the freshness test reads every one back)
  verify.json                  the verifier's report as run (the JSON the webapp serves): ok true, checks [10, each name/ok/status/detail/measured/tolerance/unit/measured_text/tolerance_text/where/skipped_reason/data], passed 10, ran 10, awaiting [], skipped [], failed [], summary, table -- the ten rows of step 2, rewritten after the passes, so the printed table and the file agree without re-running (counts read from the stub run's file by the freshness test)
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

must print the ten-row table of step 2 with every STATUS `PASS`,
no `detail:` block (a PASS is rendered once, in the table; the prose
of every check is in `verify.json`) and exit 0; the `engine_parity`
row -- and its `detail` in `verify.json`, which carries the worst
position, angle, time, reprojection, drawn-aircraft budget and label
contrast -- is the phase's engine-parity claim, and its numbers go
into this document. Then the failure demonstrations, each
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

The count must print 24 (and 24 for tower0). In `chase0\0005.png` (the
header reads "frame index 5 (6 of 24)") the yellow wing line (64.5 m
at 176 m range: 455 px wide) must lie across the rendered 747's wings
and the 59.6 m box enclose most of the fuselage (the box is the FDM's
eyepoint-to-tail-arm extent, 11 m short of the real 70.7 m, and the
header says "no fuselage length in JSBSim"), to within
the frame's graded pixel budget the verifier prints ("aircraft drawn
within x.xx m", about 10 px at this range); the horizon line must run
along the rendered horizon (the flat scene's ground plane edge) and the
lattice recede toward it; the blue track through the aircraft must be
the flown path (the telemetry, 115 points) with the 24 scheduled dots
on it, and the header band at the top must leave the rendered pixels
readable through it (alpha 96/255, not black). In `tower0\0010.png` the
aircraft is 3 km away: a 26 px span line on the rendered aircraft, the
track line along its path, no horizon in frame (the tower looks up 75
deg), the compass in the corner with N at -94.1 deg (the tower's yaw).
A frame the engine wrote at a size other than the record's gets its
overlay at the frame's own size with the intrinsics scaled and a
header note saying so -- if that note appears, the engine's resolution
setting, not the overlay, is what to check. A wing line
beside, not on, the rendered aircraft is the SAME disagreement engine
parity grades numerically, and the frame's `render.json` record says
which side (`aircraft_px` against the manifest's labelled pixel); a
horizon line off the rendered horizon is an orientation disagreement
the applied-vs-solved clause would already have failed. Round 3
changed what the text on the overlay looks like, and that is part of
what to look at: the legend (bottom left), the compass letters,
"cam yaw" / "hdg", HFOV, VFOV and every label are drawn with a 2 px
black stroke and the compass sits on a translucent disc, so they must
be readable over the rendered sky and ground (in round 2 they were
bare grey and white text and vanished over bright pixels); "boresight"
sits beside the cross, "N" beside the arrow's head, and the ring
distances sit to the right of the frame's centre, off the arrow's
column -- a label sitting on top of another, or far from the mark it
names with no leader line to it, is a placement defect to report. Write
here what was seen.

### 6. The same from the page (awaiting Windows verification)

Everything in this section is the words the page prints TODAY,
measured in this session on the honest engine stub. The block between
the `page_expected` markers is GENERATED by `scripts/examples_expected.py`
(`--page-stub-run`: the committed `examples/cameras_multi.yaml` posted
to the TestClient's `/run` with the render choice "frames", polled to
completion; the status log as `/runs/<id>` serves it, then the download
strip, the capture card and the galleries rendered under node from the
page's own functions) with every piece the child stubs named in its
preamble, and `tests/test_webapp_capture.py::
test_the_documents_page_block_matches_the_stub_run` regenerates and
compares it as the CLI blocks are compared. Nothing here has been seen
on a Windows machine yet; paste the status lines and the card back and
this section is rewritten from them.

Start the server, interpret "fly the 747 at 10000 ft and 280 kt for 12
seconds over flat ground with a chase camera and a tower camera
capturing 24 images", leave the render select on *Render frames and
clip* (the default once the bridge is built) and Run. "Over flat
ground" is not decoration: the page's scene-setting planner
(`webapp.runs.plan_scene_setting`) stages a spec whose location nobody
chose on the prairie bake, and on a machine without that bake on the
synthesised control ridge, where a stated 10000 ft refuses
`terrain.clearance` under 3299 m peaks (measured here: the example
posted without the words answers 409 `terrain.clearance`); the words
are the planner's own opt-out, so the run flies the flat scene the
CLI's `runs\demo` flew. The block is that spec posted to `/run` with
the prompt recorded on it, so its instants are the example's; the
page's spec digest (`0916ea45841b3667`) differs from the CLI's
(`cef57d752362381d`) for the same file because `/run` projects the
spec for the engine host before the digest is answered
(`project_for_ue_host`: `hold_state` false -- the render host has no
autopilot -- and `mass_held` true, the rendered-clip convention, both
recorded as edits in the review table). A prompt compiled by the
page's LLM tier may set a default the file states differently; then
the digests and the per-frame instants are that spec's and the words
are still these. The status lines must read, in order (the model-load
counts and the seconds per frame are this machine's; the page prints
EVERY status line -- `/runs/<id>` carries the whole event log, the
same list `status.json` keeps -- so a four-camera run's first lines are
not cut off), followed by the card as the block shows it:

<!-- page_expected: begin -->
Measured 2026-09-05 on Linux x86_64, Python 3.11.15 on the honest engine STUB by `scripts/examples_expected.py` (`--page-stub-run`: `examples/cameras_multi.yaml` posted to the TestClient's `/run` with the render choice "frames", the run polled to completion, exit 0, 16.33 s wall on the stub; the status lines are the run's event list as `/runs/<id>` serves it -- the page prefixes each with the local time -- the status word padded to 10 columns; the card lines are the download strip, the capture card and the galleries rendered under node from the page's own functions, one line per block element, tags stripped, a gallery's consecutive frame captions joined on one line; the run id reads `<id>`). Stubbed in the child process, and nothing else: `webapp.runs.RunManager._render` -- the commandlet pass replaced by `tests.test_webapp_capture.honest_engine`, the consume-poses pass as a Python function (the scheduled PNGs and render.json the contract specifies); `webapp.runs.encode_scheduled_clip` -- the by-product clip's ffmpeg concat call replaced by a placeholder writer: `clip.mp4` is the 3 bytes `mp4`, never an encode; `core.util.platform.find_ffmpeg` -- a fake path (no ffmpeg on this machine, none run); `core.util.platform.ue_available` -- held open (True) so the engine choices are offered and taken; `core.util.platform.ue_unavailable_reason` -- None, the same gate; `webapp.server.refuse_placeholder_mesh` -- disabled (the B747 mesh is not imported here); `webapp.runs.ensure_control_ridge` -- a no-op (the flat scene needs no raster; the bake is not run); `webapp.runs.ensure_aircraft_model` -- a no-op (the model import needs the engine); `webapp.runs.editor_running` -- False (gotcha 9's editor-lock check; no editor here); `webapp.server.manager.out_root` -- the generator's temporary directory, so the run lands there. The capture flight, the closure flight, the card, the manifest, the schedule, the previews, the contact sheets, the overlays, the verifier and the page's own JavaScript are the real code. The `clip:` line, and run.json's `clip_encoded true` / `clip_seconds 12.992`, are the playlist arithmetic (black lead-in, 24 instants, a 1 s hold) over a placeholder file, not an encode: section 5b's ffprobe on the Windows machine is the measurement. The page's `engine_parity` row's MEASURED cell is masked `x`: those digits come from the Windows run. `tests/test_webapp_capture.py::test_the_documents_page_block_matches_the_stub_run` regenerates this block and compares it as the CLI blocks are compared (exact on Linux x86_64, numbers masked elsewhere).

```
capture    solving camera geometry and capture schedule
capture    flying the spec headlessly for the capture geometry
capture    JSBSim output: jsbsim.log (5 model loads routed there for the capture flight; nothing of JSBSim's on the console)
capture    scheduled 48 frame(s) across 2 camera(s); 48 geometry preview(s) written at 1280x720, 0.077 s/frame; 2 contact sheet(s)
capture    verification PASSED (9/9 checks; engine_parity awaiting engine frames)
closure    flying the same spec closed loop for the closure report
closure    JSBSim output: jsbsim.log (10 model loads routed there for the closure flight)
closure    closure PASSED (4/4 checks)
rendering  editor pass 1 of 2: camera 'chase0', 24 frames scheduled over the 12 s run (consume-poses, -camera-index=0)
rendering  camera 'chase0': 24 of 24 scheduled frames rendered (engine stepped 11.992 s in 1439 steps)
rendering  editor pass 2 of 2: camera 'tower0', 24 frames scheduled over the 12 s run (consume-poses, -camera-index=1)
rendering  camera 'tower0': 24 of 24 scheduled frames rendered (engine stepped 11.992 s in 1439 steps)
encoding   encoding the by-product clip from camera 'chase0' (24 frames at their scheduled instants: 12.992 s of clip = black to t=0.008 s, the flight to t=11.992 s, a 1 s hold; no telemetry panel -- the panel is fps-locked)
capture    48 overlay(s): the manifest's aircraft box, ground and horizon reprojected over the rendered frames under capture/overlays
capture    verification PASSED (10/10 checks)
done       48 frames across 2 camera(s) rendered (48 scheduled, 48 verified by engine parity) + clip (by-product of 'chase0')

card (the words the page shows, one line per block; tags stripped):
  clip: a by-product of camera 0's rendered frames shown at their scheduled instants (clip time = simulation time); the frame set below is the deliverable
  downloads frames.zip 48 PNG(s) across 2 camera(s) (chase0, tower0), named by manifest index, with each camera's render.json manifest capture/capture_manifest.json: per-frame pose, intrinsics and aircraft state -- the labeled data verify.json capture/verify.json: the verification checks as run (engine parity awaits engine frames on a headless run) telemetry capture/telemetry.json: the headless flight the manifest describes clip.mp4 clip.mp4: by-product of 'chase0' (the frame set is the deliverable) everything (.zip) 162 file(s): every artefact listed below
  capture geometry — 48 scheduled, 48 rendered, 48 verified; 48 geometry preview(s) (previews at 1280x720, 0.077 s/frame; a contact sheet per camera; 48 overlay(s) of the reprojected geometry over the rendered frames) chase0 : 24 scheduled, 24 rendered, 24 verified
  tower0 : 24 scheduled, 24 rendered, 24 verified
  verification PASSED (10/10 checks) capture/verify.json CHECK STATUS MEASURED TOLERANCE WHERE
  manifest_version PASS version 1 = 1 spec 0916ea45841b3667
  fields_finite PASS 0 non-finite of 48 records 0 non-finite 48 records, 6 fields each
  geometry_recovery PASS 4.14e-13 px 0.5 px worst tower0 #4 t=2.142 s
  cross_view_consistency PASS 1.08e-12 m 0.5 m 24 two-view instants; worst sample 10 t=1.067 s (chase0 #2 with tower0 #2); rays from the poses recomputed from the spec through each record's own label, against the telemetry's aircraft
  count_exactness PASS 48 frames = 24 + 24 exactly 48 chase0 24/24, tower0 24/24
  flight_fidelity PASS t 0 s, pos 0 m, att 0 deg 1e-09 s, 1e-06 m, 1e-06 deg 48 records against 115 samples; digest f9a9ff9475181021 = output_digest; worst chase0 #0 t=0.008 s
  schedule_fidelity PASS 0 of 48 instants differ 0 differ chase0 24/24, tower0 24/24 (recorded/spec)
  pose_fidelity PASS pos 0 m, ang 0 deg, lens 0 px 1e-06 m, 1e-06 deg, 1e-06 px 48 records against the tracks recomputed from 2 camera(s) over 115 samples; digests = pose_track_digest; worst chase0 #0 t=0.008 s
  aim_fidelity PASS gap 4.14e-13 px 1e-06 px, 1e-06 deg 48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, predicted 13.7
  engine_parity PASS pos x.xxx m, ang x.xxx deg, t x.xe+xx s, px x.xx 0.1 m, 0.1 deg, 1e-06 s, 3.0 px 48 of 48 frames verified across 2 camera(s)
  closure PASSED — the same spec flown closed loop, graded over the settled half of 12 s (full duration: a frames run steps the whole flight) capture/closure.json ok altitude: commanded 3048.00 m, achieved 3048.01 m (tol 15 m)
  ok airspeed: commanded 322.74 kt TAS, achieved 322.74 kt TAS (tol 3 kt TAS)
  ok heading: commanded 0.00 deg, achieved 0.00 deg (tol 3 deg)
  ok settled: commanded 0.00 m/s, achieved 0.00 m/s (tol 1 m/s)
  chase0 : 24 scheduled, 24 rendered, 24 verified — showing 24 of 24 rendered frame(s) show the reprojected-geometry overlays (24 of 24)
  captions: #0 t=0.008 s, #1 t=0.525 s, #2 t=1.067 s, #3 t=1.608 s, #4 t=2.142 s, #5 t=2.683 s, #6 t=3.225 s, #7 t=3.767 s, #8 t=4.283 s, #9 t=4.783 s, #10 t=5.283 s, #11 t=5.783 s, #12 t=6.183 s, #13 t=6.683 s, #14 t=7.183 s, #15 t=7.683 s, #16 t=8.200 s, #17 t=8.742 s, #18 t=9.283 s, #19 t=9.825 s, #20 t=10.367 s, #21 t=10.908 s, #22 t=11.450 s, #23 t=11.992 s
  geometry previews (not frames): 24 shown, and their contact sheet
  contact sheet: every preview of this camera with its index and time
  captions: #0 t=0.008 s, #1 t=0.525 s, #2 t=1.067 s, #3 t=1.608 s, #4 t=2.142 s, #5 t=2.683 s, #6 t=3.225 s, #7 t=3.767 s, #8 t=4.283 s, #9 t=4.783 s, #10 t=5.283 s, #11 t=5.783 s, #12 t=6.183 s, #13 t=6.683 s, #14 t=7.183 s, #15 t=7.683 s, #16 t=8.200 s, #17 t=8.742 s, #18 t=9.283 s, #19 t=9.825 s, #20 t=10.367 s, #21 t=10.908 s, #22 t=11.450 s, #23 t=11.992 s
  tower0 : 24 scheduled, 24 rendered, 24 verified — showing 24 of 24 rendered frame(s) show the reprojected-geometry overlays (24 of 24)
  captions: #0 t=0.008 s, #1 t=0.525 s, #2 t=1.067 s, #3 t=1.608 s, #4 t=2.142 s, #5 t=2.683 s, #6 t=3.225 s, #7 t=3.767 s, #8 t=4.283 s, #9 t=4.783 s, #10 t=5.283 s, #11 t=5.783 s, #12 t=6.183 s, #13 t=6.683 s, #14 t=7.183 s, #15 t=7.683 s, #16 t=8.200 s, #17 t=8.742 s, #18 t=9.283 s, #19 t=9.825 s, #20 t=10.367 s, #21 t=10.908 s, #22 t=11.450 s, #23 t=11.992 s
  geometry previews (not frames): 24 shown, and their contact sheet
  contact sheet: every preview of this camera with its index and time
  captions: #0 t=0.008 s, #1 t=0.525 s, #2 t=1.067 s, #3 t=1.608 s, #4 t=2.142 s, #5 t=2.683 s, #6 t=3.225 s, #7 t=3.767 s, #8 t=4.283 s, #9 t=4.783 s, #10 t=5.283 s, #11 t=5.783 s, #12 t=6.183 s, #13 t=6.683 s, #14 t=7.183 s, #15 t=7.683 s, #16 t=8.200 s, #17 t=8.742 s, #18 t=9.283 s, #19 t=9.825 s, #20 t=10.367 s, #21 t=10.908 s, #22 t=11.450 s, #23 t=11.992 s
```

<!-- page_expected: end -->

(11.992 s is the schedule's last instant, from section 2; 1439 steps
is the count the stub's render.json records for that instant on the
120 Hz grid, the same count section 3 requires of the commandlet's
log -- a different count on Windows is a finding to report. The first
"verification PASSED" is the headless verifier before the engine
passes, 9/9 with engine parity AWAITING; the second is after them,
10/10 -- two cameras, so cross-view consistency ran. The
`engine_parity` row's MEASURED cell is masked `x` as in section 2.)

The capture card must then show, top to bottom (the block above is
the same card line for line; what follows says what each line means):

* the download strip: `frames.zip` ("48 PNG(s) across 2 camera(s)
  (chase0, tower0), named by manifest index, with each camera's
  render.json"), `manifest` (capture/capture_manifest.json),
  `verify.json` (capture/verify.json: the checks the table and the
  tally below are rendered from), `telemetry` (capture/telemetry.json:
  the headless flight the manifest describes), `clip.mp4`
  ("by-product of 'chase0' (the frame set is the deliverable)") and
  `everything (.zip)` with the file count -- one button per artefact
  class the run wrote, nothing else;
* "capture geometry — 48 scheduled, 48 rendered, 48 verified; 48
  geometry preview(s) (previews at 1280x720, the block's s/frame; a
  contact sheet per camera; 48 overlay(s) of the reprojected geometry
  over the rendered frames)";
* one gallery per camera headed "chase0: 24 scheduled, 24 rendered,
  24 verified — showing 24 of 24 rendered frame(s)" with the checkbox
  "show the reprojected-geometry overlays (24 of 24)", then all 24
  rendered frames captioned "#0 t=0.008 s" ... "#23 t=11.992 s" (the
  manifest's instants) as the FIRST pictures under that heading, and
  the previews -- with their contact sheet, which is a mosaic of
  previews -- only behind "geometry previews (not frames): 24 shown,
  and their contact sheet"; the same for tower0. The count in a
  heading is always the number of pictures under it. No caption
  carries the words "parity FAIL" and no thumbnail has a red outline:
  a frame the verifier rejects is captioned "#k t=... s — parity FAIL:
  <the verifier's own sentence for that frame>" in red with a red
  outline, and the heading adds "N of them failed engine parity
  (captioned and outlined below)", N equal to rendered minus verified
  (`verify.json`'s engine_parity data now records one entry per graded
  frame under "frames": index, t_s, ok, the measured gaps and that
  frame's problem sentences -- measured on the drifting stub, section
  6b);
* "verification PASSED (10/10 checks)", the link `capture/verify.json`
  beside it (the file the table is rendered from), over the CHECK /
  STATUS / MEASURED / TOLERANCE / WHERE table -- the same rows
  `flightsim.verify` prints -- with every row PASS; the engine_parity
  row's MEASURED reads "pos x.xxx m, ang x.xxx deg, t x.xe+xx s, px
  x.xx" against "0.1 m, 0.1 deg, 1e-06 s, 3.0 px" and its WHERE "48
  of 48 frames verified across 2 camera(s)" (the stub measured pos
  0.000 m, ang 0.000 deg, t 0.0e+00 s, px 0.00; the real engine's
  numbers must sit under the tolerances);
* "closure PASSED — the same spec flown closed loop, graded over the
  settled half of 12 s (full duration: a frames run steps the whole
  flight)", the link `capture/closure.json` beside it, with each row's
  unit ("altitude: commanded 3048.00 m, achieved ... m (tol 15 m)").

Then, from a shell, the frame set as its own download and what a
restart does to the run:

```
curl -s -o frames.zip http://localhost:8008/runs/<id>/frames.zip
tar -tf frames.zip | find /c ".png"
tar -tf frames.zip | find /c "render.json"
curl -s http://localhost:8008/runs/<id>/files | python -c "import json,sys; d=json.load(sys.stdin); print([x['class'] for x in d['downloads']]); print([(g['camera_id'], len(g['frames']), len(g['previews'])) for g in d['galleries']])"
```

The counts must print 48 and 2, the classes `['frames', 'manifest',
'verification', 'telemetry', 'clip', 'everything']` and the galleries `[('chase0',
24, 24), ('tower0', 24, 24)]`. Stop the server, start it again, reload
the page: the same run id comes back "done" with the same card (the
events end with "recovered after a server restart"), because a
finished run's verdict and event log are in `<run>/status.json` and
its card is rebuilt from the manifest, `capture/verify.json`,
`capture/run.json`, `capture/closure.json` and `provenance.json` --
measured here: the recovered summary equals the live one key for key
for both a headless and a stubbed frames run. A headless run (render
select on *Headless*) must show the SAME card with "48 scheduled, 0
rendered (headless: no engine pass); 48 geometry preview(s), which
are NOT frames", each gallery headed "chase0: 24 scheduled, 0
rendered (headless), previews only" and "previews (fallback: headless
run by choice; choose Render frames and clip for the frame set;
showing 24 of 24 preview(s), which are NOT frames)" (on a machine
without the engine the fallback is the platform gate's own sentence,
once -- measured here: "previews (fallback: no engine on this OS: the
render half needs macOS, or Windows with Unreal Engine 5.5 and the
FlightSimBridge built; showing 4 of 4 preview(s), which are NOT
frames)" -- never prefixed with a second "no engine" clause), the
closure heading "graded over the
settled half of 12 s (the first 12 s, the same window a clip would
cover, capped at 22 s)" -- a headless run has no clip to name, so
`closure.json` records window "capped" with `spec_duration_s` beside
`duration_s` (a *Clip only* run reads "the first 12 s, the clip's
window, capped at 22 s"; a 120 s flight "the first 22 s of the 120 s
flight, ..."; the frames run above "full duration: a frames run steps
the whole flight"), no frames.zip button, and
`/runs/<id>/frames.zip` must answer 404 "no rendered frames: this was
a headless run (no engine pass); the manifest and the previews are
its deliverable".

#### 6b. If an engine pass fails on the Windows machine

A failed run is terminal for the page exactly like a finished one: the
page must NOT fall back to the status text. Measured here on the honest
stub with camera 0's pass cut to 3 of 4 frames (the same payloads a
short or crashed commandlet pass produces): the status ends
`failed  [render.frames] camera 'camera0': the engine captured 3 of 4
scheduled frames against the 4 the card scheduled`; the clip area
reads "no clip: the run FAILED before a clip was encoded — <that
line>"; the card reads "capture geometry — 8 scheduled, 3 rendered, 3
verified (engine pass FAILED: <that line>); 8 geometry preview(s)
..." with "verification FAILED (9/10 checks; FAILED: engine_parity)"
and the engine_parity row's WHERE naming the shortfall; the strip
offers `frames.zip` ("3 PNG(s) across 1 camera(s) (camera0)"),
`manifest`, `verify.json`, `telemetry` and `everything` -- no clip
button, since none was encoded; camera0's gallery is headed "4
scheduled, 3 rendered, 3 verified — showing 3 of 3 rendered
frame(s)" and tower0's "4 scheduled, 0 rendered, 0 verified" over
"previews (fallback: the engine pass rendered no frame for this
camera (the run's status names the failure); ...)"; the files panel
lists every file the run wrote, `status.json` and the per-camera
`render.log` included. On Windows, with the real commandlet, the
words are the same with the run's own numbers; a mid-run capture
refusal (a camera placed in the terrain) shows instead "capture
refused — [camera.terrain_clearance] ... (measured X m AGL, limit Y m
AGL)" with "the run ended failed on this refusal; every file it wrote
before refusing is listed below" and the four files it wrote
(provenance.json, scenario.yaml, status.json, jsbsim.log) one click
away.

A DISHONEST pass -- every PNG present, the counts right, but the
engine's render.json placing frame 1 of each camera 20 cm east of the
solved pose (the stub in `tests/test_webapp_capture.py`,
`drifting_run`) -- ends `failed  [render.frames] engine parity ...
0.200 m ...` with "8 scheduled, 8 rendered, 6 verified"; each gallery
is headed "4 scheduled, 4 rendered, 3 verified — showing 4 of 4
rendered frame(s) — 1 of them failed engine parity (captioned and
outlined below)", the one red-outlined thumbnail is
`capture/frames/<camera>/0001.png` and its caption reads "#1 t=<its
instant> s — parity FAIL: applied position 0.200 m from the solved
pose (tol 0.1)" -- the sentence `verify.json` records for that frame
(`checks[engine_parity].data.frames.<camera>[1].problems[0]`); two
"parity FAIL" captions across the run, equal to rendered minus
verified. An honest pass has none, and a headless run's `verify.json`
records no frame at all (`data.frames` is `{}`).

#### 6c. Refusals, the review table and a lost file listing (page round 3, 2026-09-05)

Every refusal the page prints has ONE shape, the validation verdict's:
`[constraint] message (requested X unit, limit Y unit)` -- rendered by
one function (`refusalWords`) for the pre-run verdict, a `/run`
refusal in the status line, and a mid-run capture refusal in the card
(verb "measured"). Every 409 the server answers carries the verdict's
keys (`constraint`, `message`, `actual`, `limit`, `unit`) beside the
keys it always had. Measured live through the test client on this
machine:

```
refused — [ue.platform] no engine on this OS: the render half needs macOS, or Windows with Unreal Engine 5.5 and the FlightSimBridge built (requested frames, limit none (Headless))
refused — [preview.scale] preview.scale: 3 does not divide 1280x720 exactly (426.67x240); the preview draws at 1/N of the record's resolution and never floors a size (camera camera0) (requested 3, limit divides 1280x720)
refused — [aircraft.mesh] the f15 has real flight physics but no licensed 3-D model is configured for it, and placeholder airframes never render. Airframes with a model this machine can build: A320, B747, DHC6, c172p. (requested f15, limit A320, B747, DHC6, c172p)
refused — [render.host_parity] turbulence 'moderate': same-seed host parity is measured and refused for turbulence realisations (docs/VALIDITY.md), so the aircraft the engine draws cannot be labelled from the manifest; choose 'Clip only' (visual-only, seed recorded) or turbulence none (requested frames, limit clip or none (the choices whose labels need no host parity))
refused — [render.choice] render must be one of frames, clip, none (requested video, limit frames, clip, none)
refused — [run.busy] a run is already rendering (abc123def456); one editor instance at a time (requested abc123def456 rendering, limit one editor instance at a time)
```

Each constraint appears exactly once in its line; the CLI's six-line
`REFUSED ue.platform` paragraph (still the payload's `refused` text,
for the CLI) reaches the page nowhere. The pre-run verdict prints a
violation's unit on both numbers ("(requested 50000 ft, limit 45000
ft)"), as `flightsim.capture` does.

The review table escapes everything it interpolates (values, units,
sources, the provenance note's quoted phrase, notes, warnings): a
prompt phrase with a double quote or "<" reaches the table as text and
an input's value attribute survives it (measured: 'B7"47<x>' and
'tow"er<0>' round-trip through `editedSpecDict` unchanged). Each
camera's keyframed moves are rows "move k of N" whose every keyed
field is an input (t_s first, the field's own unit) writing back into
`cameras[i].moves[k]`; their source column is the list's RECORDED
provenance (`moves_source` / `moves_from` on the camera record, one for
the whole list, serialised beside it and digest-relevant like every
source; `CameraSpec.set_moves` records it) in that source's colour, or
"spec data (no recorded source)" in the default colour -- never the
user's green for a source nobody recorded. An edit records the list as
"user" / "edited in the web UI" and `/run` re-parses it (a source word
outside `user/inferred/model/derived/default` is refused by name).

A file listing that does not arrive is said by name where the strip
would be: "files: /runs/<id>/files answered HTTP 500 — downloads and
galleries unavailable", "... could not be fetched (<the error>) — ...",
or "files: this run listed no files (... answered an empty list) —
nothing to download, no gallery to show"; the card keeps its count
list, and the flight path says "the file listing did not arrive (the
files panel says why)" rather than "this run listed no telemetry
file".

**On the Windows machine** (nothing above was seen on a real engine):

1. Run the section-6 spec with *Render frames and clip*. The
   galleries must show NO "parity FAIL" caption and no red outline;
   `curl -s http://localhost:8008/runs/<id>/file/capture/verify.json |
   python -c "import json,sys; d=json.load(sys.stdin); c=[x for x in
   d['checks'] if x['name']=='engine_parity'][0]; print({k: [f['ok']
   for f in v] for k, v in c['data']['frames'].items()})"` must print
   every camera's list as all `True`, 24 entries each.
2. To see a FAIL caption on purpose: edit
   `runs\<id>\capture\frames\chase0\render.json`, add 0.2 to
   `frame_records[1].camera_applied_east_m`, run
   `.venv\Scripts\python -m flightsim.verify runs\<id>\capture` (exit
   code 1, engine_parity FAIL naming "chase0 frame 1: applied position
   0.200 m from the solved pose (tol 0.1)"), reload the page: chase0's
   gallery must read "24 scheduled, 24 rendered, 23 verified — showing
   24 of 24 rendered frame(s) — 1 of them failed engine parity
   (captioned and outlined below)" with `0001.png` outlined and
   captioned "#1 t=<the manifest's instant for frame 1> s — parity FAIL:
   applied position 0.200 m from the solved pose (tol 0.1)". Restore
   the file and re-run the verifier afterwards.
3. Interpret the same prompt with "in moderate turbulence", leave
   *Render frames and clip*, press Run: the status must read exactly
   the `[render.host_parity]` line above (one constraint, the value
   clause at the end).

### 7. Temporal alignment on rendered frames

```
.venv\Scripts\python -m flightsim.capture examples\cameras_multi_cockpit.yaml --out runs\demo_b --render frames
.venv\Scripts\python -m flightsim.verify runs\demo_b --against runs\demo
```

`examples\cameras_multi_cockpit.yaml` is the committed second camera
set (the same flight, one cockpit camera, 24 images); the
`temporal_alignment` row must read `PASS  0 s  1e-09 s  24 instants in
both runs; worst gap 0 s` with identical `simulation_digest` and
`output_digest`, now on rendered frames -- the same table the Linux
run above shows without them.

Paste every log back; this section is rewritten from them.

## Known limitations

* Keyframed moves only — no physically simulated camera platforms (out
  of scope by the phase definition).
* The headless CLI's tornado hazard check uses the straight-line
  45%-ahead placement (its own track IS straight); the webapp's
  terrain runs refine the placement onto the pre-flown banked track
  through the same shared helper.
* **A run the server died under is not recovered.** A finished run
  writes `<run>/status.json` (its verdict and event log) before its
  status shows as done or failed, and a restarted server rebuilds the
  run -- headless, clip or frames -- from that file, `provenance.json`
  and the capture files; a run interrupted by the restart has none and
  the page says "not recoverable" (gotcha 23 stands: do not restart
  the server while a run is active). Runs written before status.json
  existed recover from their clip.mp4 alone, with no capture card.
* **Keyframed moves reach the page only from a spec that carried
  them.** No prompt vocabulary produces `moves` (the compiler's camera
  schema has none), so the review table's keyframe rows -- editable,
  with the list's recorded provenance -- appear only for a spec loaded
  with moves (the CLI's YAML path, or a run's `scenario.yaml` re-posted
  to `/run`); a prompt cannot state a dolly yet.
* **The page's galleries draw every rendered frame the server lists**
  (lazily loaded; 48 thumbnails at 160 px is the measured largest
  case here) but previews stay capped at MAX_PREVIEWS (60) per run,
  and the card says so ("previews capped at 60; the manifest carries
  every frame"). The overlay toggle swaps each thumbnail for the
  overlay file the server listed; nothing is drawn in the browser.
* Cross-view consistency is SKIPPED by name for single-camera runs
  (`ok` None, reason "single camera": counted in neither passed nor
  ran -- no false pass, no false failure); the two-camera example is
  where it is exercised.
* **Where JSBSim's console is and is not routed.** The startup banner
  JSBSim prints from C++ on every `FGFDMExec` construction is routed
  at the file-descriptor level (`core/fdm/console.py`) ONLY inside a
  sink: the CLI's whole run (`<out>/jsbsim.log`) and, since round 2,
  the page's whole run flow (`<run>/jsbsim.log`, entered by the run
  manager around planning, the capture and closure flights and the
  card; listed on the page as an artefact) or, for a `capture_run`
  called directly with no sink, `capture/jsbsim.log`. Every routed
  load is preceded by a stamp, `# load 3: FlightDynamics(B747) called
  from core.scenario.validate.validate`, so fourteen identical banners
  read as fourteen named loads (measured: the CLI's cameras_multi run
  is 14 stamped loads, 15 with `--card` or `--render frames`, the
  fifteenth being the run card's engine-start mixture probe, stamped
  `FGFDMExec(B747, mixture probe) called from core.scenario.card.
  attempt`; a page capture run of the 3 s prairie spec is 15 in
  `<run>/jsbsim.log`). The probe builds its model at JSBSim's debug
  level 1, so `run_ic` prints the Mass Properties Report from C++
  AFTER the banner; until docs round 1 (2026-09-05) only the probe's
  construction was inside the sink and that report -- twelve coloured
  lines -- landed on stdout between the header and `card:`, one line
  above "nothing of JSBSim's on stdout" (measured on `--card --render
  none`: 96 stdout lines). The whole probe (construction, `run_ic`,
  trim, the sustain steps) is routed now: 82 lines, none of JSBSim's,
  and the report sits in the log under the probe's stamp;
  `tests/test_camera_cli.py::
  test_the_cards_engine_start_probe_prints_nothing_on_stdout` pins it
  under file-descriptor capture. Since round 3 the request handlers' own
  pre-flight planning and validation BEFORE a run exists
  (`plan_flyable_defaults`, the envelope measurement, `validate` in
  `/compile`, `/run` and `/capture`) is routed too, to the
  server-level planning log `<runs root>/jsbsim.log` (appended,
  stamped, counted; `/status` names it as `planning_log` with
  `planning_model_loads`), and the sink is one slot PER THREAD
  (`threading.local`), so a request planning while a run is flying
  keeps its own slot and the run keeps its own log with its own
  numbering from 1. NOT routed: a bare `run_spec` in a test with no
  sink entered. The descriptor redirection itself is process-wide for
  the milliseconds one construction takes, so two threads constructing
  at the same instant could land a banner in the other's log -- in a
  log, never on the console.
* **What the verifier cannot see.** `flight_fidelity` and
  `schedule_fidelity` read `telemetry.json` and `scenario.yaml` beside
  the manifest; a manifest verified without them is graded for its
  internal consistency only (the two checks SKIPPED by name, never
  passed). `flight_fidelity` proves the manifest IS the telemetry
  beside it (digest and per-sample equality); it cannot prove that
  telemetry was flown honestly -- a `telemetry.json` and manifest
  forged together verify, and only engine parity on rendered frames
  (Windows, awaiting) grades the pixels. `schedule_fidelity` recomputes
  the schedule with the scheduler the producer used (`core/capture/
  schedule.py`) and `pose_fidelity` (round 3) recomputes the pose
  tracks with the pose solver the producer used (`core/capture/
  poses.py`), so a bug in the scheduler or the solver itself is caught
  only by their own tests (and, for the pose, by engine parity on
  rendered frames), not by these checks; what they prove is that the
  manifest carries what the committed spec commands over the recorded
  flight. The projections the verifier grades WITH (the aircraft's
  north/east from lat/lon, the pinhole model, the rays) are its own
  (pyproj and plain arithmetic), never the solver's.
* The `--brief` schedule line for a count schedule states the spacing's
  range and "sample-snapped, not uniform": the instants are snapped to
  telemetry samples (13 fixed steps apart), so no period is claimed. A
  distance, proximity or event schedule is worded from its trigger
  ("every 400 m of track; instants 6.600..7.433 s apart"): the spacing
  is the flown track's, not the sampling's.
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
  a silhouette, and its LENGTH is a lower bound: the larger of the
  FDM's stated-station extent (eyepoint to tail arm, 59.6 m for the
  B747 whose fuselage is 70.7 m) and the wing-to-tail arm plus one
  mean chord (6.3 m for the c172p, whose fuselage is 8.3 m), because
  JSBSim states no nose-to-tail length; the picture's header says
  ">= ... (no fuselage length in JSBSim)" and the manifest names every
  station. The span (metrics/bw-ft) is the airframe's own.
* The overlays have been drawn over the honest engine stub only; over
  real rendered pixels they are NOT YET RUN (step 5c above).
* The terrain skyline cull hides ground behind nearer ground per image
  column from the wireframe's own samples: a ridge narrower than the
  coarse spacing (720 m on control_ridge) between two sample rows does
  not occlude, and a farther sample within 1 px of the skyline is kept
  (`SKYLINE_TOLERANCE_PX`). The fine lattice near the camera (180 m)
  narrows that gap only within 7.2 km. The cull orders samples by
  their camera depth interpolated linearly along each segment, not
  perspective-correctly; over a 720 m segment that is a metre-scale
  depth error, far below the 1 px tolerance at the ranges drawn.
* The north arrow's world length is set by its projected size and
  capped at 0.3 x its base's depth: where north is foreshortened to
  nothing (the flat chase view's arrow base 36 km out) it is shorter
  than 60 px (45 px there) and the compass rose carries the
  orientation; the header's compass numbers are the record's yaw and
  heading, never estimated from the arrow.
* The telemetry track is decimated by an integer stride to at most
  10 Hz and never interpolated; the recorder's own spacing (13 fixed
  steps, 9.23 Hz) is below that, so today's tracks are undecimated and
  the header says so.
* Segmentation masks, bounding boxes, domain randomization, batch
  execution: out of scope, untouched.
