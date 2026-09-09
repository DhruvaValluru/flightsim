# Camera Phase 2 — Windows-first capture: plan

Supersedes the cross-platform demonstration story in
`docs/CAMERA_PHASE1_REPORT.md`. This plan does two things at once: it
retargets the visible deliverable from a platform-independent geometry
preview to **real rendered frames on Windows**, and it closes the
defects found auditing Phase 1 against its own exit criteria.

## The decision that drives everything

Phase 1 accepted a constraint — "the demonstration must not require
macOS" — and paid for it with a preview renderer that draws the scene
as single pixels. Measured on the committed example
(`examples/cameras_multi.yaml`), one preview frame carries **128
non-background pixels on a 640×360 canvas** below its caption: 64 track
pixels, 40 for an unfilled circle marking the aircraft, ~24 terrain
dots. That is not a picture of a camera view. It cannot show attitude,
it has no horizon, and no one can look at it and tell a correct pose
from a wrong one.

Windows now has the engine (`e73aee8`: Win64 host, `ue_available()`
returns true on Windows with the bridge built). So the constraint is
gone, and with it the reason the preview existed.

**Assumption, stated because it changes scope:** "Windows only" here
means Windows is the single *supported, tested and documented* path for
the capture → render → verify demonstration. The macOS code paths are
the same C++ and cost nothing to leave standing, so they stay, untested
and unadvertised. Nothing is deleted merely to make the tree
Windows-shaped. Off-Windows, the visual half refuses by name and the
geometry half still runs (it is how the suite runs in CI on Linux).

## Two structural moves

Everything below follows from these.

### Move 1 — the manifest becomes the render contract, not a sibling document

Today `capture_manifest.json` is written by `flightsim/capture.py` and
by nothing else, while pixels are produced by a completely separate
webapp path that maps the spec's first camera back to the old
`-camera=<word>` / `-chase=<triple>` preset flags and lets C++ recompute
the pose per frame. The two artifacts never meet. The commandlet's FOV
is hardcoded (`FlightSimRenderCommandlet.cpp:797`,
`Capture->FOVAngle = bVisual ? 55.0f : 24.0f`) and its resolution comes
from `-width`/`-height`, so the intrinsics in the manifest describe an
image that was never rendered.

After: the commandlet takes `-manifest=<path> -camera=<id>`, reads the
poses, the intrinsics and the capture times from it, sets its render
target from `width_px`/`height_px`, derives FOV from `fx_px`, and writes
exactly the files the manifest names into `frames/<camera_id>/`.
Divergence between the recorded geometry and the rendered geometry stops
being a tolerance to check and becomes unrepresentable.

### Move 2 — one flight, not two

`flightsim.capture` flies JSBSim headlessly and solves poses over *that*
telemetry. The webapp render flies JSBSim again inside the UE host. The
manifest therefore describes flight A while the pixels come from flight
B. Every label is wrong by whatever the two runs differ by, and nothing
in the tree measures that difference.

The pipeline becomes explicitly three passes over **one** recorded
flight:

1. **fly** — run the scenario once, record `telemetry.json`;
2. **solve** — poses, schedules, validation, manifest, from that
   telemetry;
3. **render** — replay that same telemetry, consume the manifest
   verbatim, emit the named frames.

Pass 3 needs the aircraft placed from the recorded track rather than
re-simulated. Before building that, **measure**: run the UE host twice
on the same card and compare `output_digest`. If the host is already
bit-deterministic, pass 3 can re-fly instead of replaying and the
verifier asserts the digests match. If it is not, replay is required.
Either way the property is checked, not assumed.

### The measurement, taken

Taken on `examples/cameras_multi.yaml`, Windows, UE 5.5. A two-camera
run renders one commandlet pass per camera, so it is two host flights
over one card — the measurement the paragraph above asks for, and it
now runs on every multi-camera render rather than once by hand.

**The host is bit-deterministic.** Both passes produced byte-identical
telemetry across all 30 recorded columns and 120 samples, SHA-256
`4e5a7334…` both times, worst per-sample difference exactly `0`. So
**re-flying is sound and `-replay=` is not needed.** `verify_host_determinism`
asserts it on every run that renders more than one camera, digesting
with `repr` so a last-bit divergence fails; NOT RUN on a single-camera
render, which measures nothing about repeatability.

**But the host's flight is not the pre-run's flight.** The headless
pre-run (the `jsbsim` Python package) and the host (UE's vendored
JSBSim) are different builds stepping the same scenario, and they
diverge: **1.38 m** worst, at t≈1.5 s, over the demo's 46 gradeable
frames. That is the real size of P10, measured for the first time, and
it is what the manifest's aircraft labels are wrong by.

Consequence for the planned `capture.telemetry_mismatch` refusal, which
W1 specifies as "the render's own recorded telemetry digest must equal
the digest the manifest was solved against": **that refusal is not
implementable while the host re-flies**, because the two digests are
never equal — 1.38 m apart is not a last-bit difference. It presupposes
the replay path. Determinism removed the *reproducibility* argument for
replay but not the *agreement* one, so what stands in its place today
is `flight_agreement`, which bounds the divergence at 25 m against the
host's own recording and now reports a real number instead of comparing
the pre-run with itself. Closing P10 outright still means either
replaying the recorded track into the host, or rebuilding the manifest's
aircraft states from the host's telemetry after the render.

**Closed, by a third route neither of those.** Both options above accept
that the poses are solved over the wrong flight and then repair the
labels afterwards. The determinism measurement licenses something
simpler: let the host fly the card FIRST — the telemetry-only commandlet,
no renderer, `scripts/run_ue_scenario.ps1`, which has existed since
Phase 5 — and solve the poses, schedules, scene checks and manifest over
THAT recording. The render passes then re-fly the same card and, being
bit-deterministic, fly the identical flight. Manifest and pixels
describe one flight by construction, with no replay path and no
post-hoc relabelling.

* **No new C++.** The host already records every channel the pose solver
  needs (`t`, `lat_deg`, `lon_deg`, `altitude_m`, `roll_deg`,
  `pitch_deg`, `heading_deg` — `FlightSimTelemetryRecorder.cpp` lines
  24–33 against `core/capture/poses.py:74`), under the same names and
  units. `core/capture/hostflight.py` reads it back and refuses by name
  (`capture.host_flight`) when it cannot be solved over.
* **The pre-run is kept, and demoted.** It stays the cheap pre-flight
  gate, so a camera inside a mountain still refuses before any engine
  time is spent. It is no longer a data source. The scene checks then
  run AGAIN over the host's own track, because that is the flight the
  frames are taken on.
* **The manifest declares which flight it describes.** `solve_source`,
  new in `manifest_version` 3 — a v2 manifest could not say, and always
  meant the pre-run. A consumer training on these images needs to know.
* **The decision keeps checking its condition.** Every rendered run now
  records the solve flight plus one per camera pass, so
  `verify_host_determinism` compares them and no longer reports NOT RUN
  on a single-camera render. And `verify_flight_agreement` reads
  `solve_source`: a manifest claiming a host solve is held to 0.5 m
  rather than 25 m, so a silent fallback to the pre-run — the pass not
  running, `--no-host-flight`, a future refactor — FAILS by name at its
  own 1.38 m signature instead of passing inside a tolerance sized for
  it. That bound is pinned by test in both directions.
* **What is NOT yet measured.** The 0.5 m bound is reasoned from the
  interpolation residual (the track's curvature over half of a 0.1 s
  host sample, sub-decimetre even in a hard manoeuvre), not measured on
  Windows. Nor is the assumption that the solve pass and the render
  passes fly the same flight despite differing in `-Visual`: the solve
  pass is given the physics-affecting flags (`-terrain=`,
  `-GeorefTerrain`) and not the render-scene one. `host_determinism` is
  exactly the check that grades that choice, and a FAIL there naming
  `host_flight` as the odd one out means `-Visual` perturbs the flight
  and the solve pass must carry it too.

## Problems being closed

Each was reproduced against the committed tree, not inferred.

| # | Problem | Evidence | Closed by |
|---|---|---|---|
| P1 | Cross-view consistency cannot fail | passes with a camera displaced 300 m, with all focal lengths ×1.7, and with aircraft states swapped between cameras; error is exactly `0.0000 m` | W5 |
| P2 | Geometry recovery only projects the aircraft, on the optical axis, and cannot see intrinsic error | ×1.7 focal scaling passes every check; quat-vs-euler gap is `0.0000 px` because `quat = euler_to_quat(roll,pitch,yaw)` | W5 |
| P3 | Count exactness never reads the requested count | spec `capture_count` set to 999 with 24 frames emitted: PASS | W5 |
| P4 | The documented verify command silently omits temporal alignment | `flightsim.verify runs/demo` prints 5/5 without ever running check 1 | W5 |
| P5 | The render path does not consume solved poses | `webapp/runs.py:camera_render_flags` emits `-camera=`/`-chase=`; nothing in the tree passes `-camera-index` | W2, W3 |
| P6 | Rendered intrinsics ≠ manifest intrinsics | FOV hardcoded 55°; manifest default implies 54.43°; ≈7 px error 600 px off centre, unchecked. Resolution accepted to 8192 px, always rendered at 1280×720 | W2 |
| P7 | No run produces pixels *and* a capture manifest | `capture_manifest` appears only in `core/capture/` and `flightsim/capture.py` | W2, W3 |
| P8 | Per-camera render passes are not runnable software | neither `render_ue_scenario.ps1` nor `.sh` accepts `-camera-index`; both manage a flat `frame_*.png` directory against a manifest promising `frames/<camera_id>/` | W3 |
| P9 | Windows entry points never mention the camera demo; the `ue.platform` refusal tells Linux users to run a `.ps1` | `deploy_windows.ps1`, `setup.ps1`, `core/util/platform.py:UE_PLATFORM_REFUSAL` | W6 |
| P10 | Two independent simulations; the manifest labels a different flight than the pixels | headless `run_spec` vs the UE host's own JSBSim run | W1 |
| P11 | The preview is 128 lit pixels and shows no attitude | measured above | W4 |
| P12 | The report overclaims | "the circular formulation is documented and avoided"; "written for EVERY captured run"; "rendering is macOS-only" | W8 |

## Work packages

Ordered so each one is provable when it lands. Repo convention holds
throughout: every new safeguard gets a named refusal and a mutation
guard in `scripts/mutation_check.sh`.

### W1 — One flight (P10)

- Add `scripts/capture_windows.ps1`: the single instructor command. Fly,
  solve, render, verify, print a summary.
- Add `--render` to `flightsim.capture`. On Windows with the bridge
  built it drives the commandlet; anywhere else it refuses by name and
  the geometry half still completes.
- Measure host determinism: render the same card twice, compare
  `output_digest`. Record the answer in this document.
- If non-deterministic: add `-replay=<telemetry.json>` to the
  commandlet, placing the aircraft from the recorded track per
  substep instead of stepping the FDM.
- Refusal `capture.telemetry_mismatch`: the render's own recorded
  telemetry digest must equal the digest the manifest was solved
  against, or the run refuses. This is the guard that makes P10
  impossible to reintroduce.

**Proven by:** a test that corrupts the render's telemetry digest and
confirms the refusal; the mutation guard that disabling the check makes
that test pass.

### W2 — The manifest is the render contract (P5, P6, P7)

- `-manifest=<path> -camera=<id>` on `FlightSimRenderCommandlet`.
- Render target from `width_px`/`height_px`; horizontal FOV from
  `2*atan(width_px / (2*fx_px))`, per frame, so keyframed focal-length
  moves actually apply. Delete the hardcoded `FOVAngle` on this path.
- Frames written to the exact relative paths the manifest names.
- Extend the applied-vs-solved guard beyond position: rotation
  (quaternion angle) and intrinsics (fx, fy, width, height) each with a
  stated tolerance and a named refusal `camera.applied_divergence`.
- `render.json` gains the applied intrinsics per frame so the Python
  side can grade them.

**Proven by:** on Windows, a rendered run whose `render.json` intrinsics
equal the manifest's within tolerance; a test that perturbs one and
confirms the refusal.

### W3 — Per-camera passes as real software (P5, P8)

- Rewrite `scripts/render_ue_scenario.ps1` to read the camera list from
  the manifest and loop, one invocation per camera, each with its own
  `-frames=` directory; clean and count `frames/<camera_id>/` rather
  than a flat `frame_*.png` glob.
- Route the webapp's camera renders through the manifest path; retire
  `camera_render_flags` for specs that carry cameras. Keep the
  byte-identical legacy flags for camera-less specs so the existing
  pinning test still holds.

**Proven by:** a two-camera example producing two populated per-camera
directories with counts matching the manifest; the existing
camera-less argument-pinning test still passing untouched.

### W4 — Kill the dot preview; ship the real picture (P11)

- Delete `core/capture/preview.py` as a deliverable.
- Replace with `core/capture/overlay.py`: draw the manifest's geometry
  **on top of the actual rendered PNG** — a crosshair at the aircraft's
  projected position, labelled landmark markers, a projected horizon
  line, and a caption carrying camera id, sim time and focal length.
  This is simultaneously the demonstration image and the visual proof
  that the labels land where the pixels are.
- Draw the aircraft as an oriented three-axis body glyph (nose, wings,
  fin projected through its recorded attitude), not a circle, so the
  cockpit-inherits-roll property is visible rather than merely
  recorded.
- Keep a wireframe-only mode (filled, depth-sorted terrain polygons
  with per-cell Lambert shading, plus horizon and sky) for the Linux CI
  path, clearly labelled as a debug view and not as the deliverable.

**Proven by:** an overlay frame where the crosshair sits on the rendered
aircraft silhouette, measured — reuse `silhouette_bank_degrees` /
`measure_frames` from `experiments/gate5_ue_parity.py` to find the
silhouette centroid and assert the crosshair is within a stated pixel
distance of it.

### W5 — Verification that can fail (P1, P2, P3, P4)

The single highest-value package. Current checks compare the producer's
arrays against themselves.

- **Landmarks.** Python picks known world points from the terrain
  raster — the four corners and the highest cell, exact
  `(north, east, alt)` from `Heightfield.georeference` — and writes them
  into the manifest. These are off-axis, static, and known
  independently of the camera.
- **Geometry recovery** becomes: reproject each landmark through each
  frame's recorded pose and intrinsics, and compare against the
  **engine's own** `ProjectToPixel` output for the same landmark in
  `render.json`. Two implementations, two languages, two math paths,
  one answer, stated pixel tolerance. This is the independent
  implementation the phase exit criterion actually asked for. The
  `AddLandmark` hook already exists at
  `FlightSimRenderCommandlet.cpp:1333` and Gate 6 already consumes it —
  it needs a manifest-supplied landmark set, not new machinery.
- **Cross-view consistency** becomes: triangulate a *static landmark*
  seen from two cameras. Two cameras looking at the same fixed point
  from different places give genuinely independent rays. The current
  formulation — both rays cast through each record's copy of the same
  aircraft array — returns the input by construction.
- **Count exactness** reads `block["spec"]["capture_count"]["value"]`,
  the number the user asked for, not `len(schedule)`.
- **Temporal alignment** runs by default. `flightsim.verify` learns
  `--camera-sets` so one command captures the same spec twice with
  different cameras and grades the alignment, instead of alignment
  being opt-in behind `--against`.
- Any check that did not execute reports **NOT RUN** and is excluded
  from the `n/n` tally rather than counted as a pass.

**Proven by:** the corruption battery I ran becomes a test file —
displaced camera, scaled focal length, swapped aircraft states,
inflated requested count — each asserting a FAIL. Every one of those
currently passes. Plus a mutation guard per check.

### W6 — Windows plumbing and honest refusals (P9)

- `deploy_windows.ps1` and `setup.ps1` end by naming the camera demo
  command.
- `UE_PLATFORM_REFUSAL` rewritten Windows-first, and it stops telling
  Linux users to run `ue_preflight.ps1` — Linux has no UE half at all
  and should be told that.
- `ue_preflight.ps1` gains a camera-render check: engine present,
  bridge built, manifest-consuming commandlet available.

### W7 — Examples and the single command (demonstration)

**Done, and the shape of it changed.** The frames were not showing
anything for a reason no example could fix: the camera path never
passed `-Visual`, so it rendered in Gate 5's black void whatever the
example said. With the visual scene on, `cameras_multi.yaml` over the
synthesised ridge refuses by name — `camera.terrain_clearance`,
"requested −2802.8 m AGL", because its tower sits at 80 m MSL and the
ridge under it reaches ~2883 m. That refusal is correct, so the example
was not re-baselined; `examples/cameras_terrain.yaml` is the one
placed for terrain, and it renders the aircraft over a lit ridge with a
horizon. `scripts/capture_windows.ps1` is the single command.

- ~~`examples/cameras_multi.yaml` re-baselined over real baked terrain so
  the rendered frames show something.~~ Superseded: it stays the flat
  example, and it is a refusal demonstration over terrain.
- Keep `cameras_refusal.yaml`; add an intrinsics-divergence refusal
  example.
- One command end to end:
  `.\scripts\capture_windows.ps1 examples\cameras_multi.yaml runs\demo`
  → telemetry, manifest, per-camera rendered frames, overlays, and a
  pass/fail verification summary.

### W8 — Documentation (P12)

Rewrite `docs/CAMERA_PHASE1_REPORT.md` (or supersede it) to remove:

- "the circular formulation is documented and avoided" — it was not;
- "written for EVERY captured run, on every platform" — it is written by
  one CLI and never for a rendered run;
- "rendering is macOS-only" — Windows renders since `e73aee8`.

State plainly which checks measure pixels, which measure geometry only,
and what is untested off Windows.

## What can be built where

- **All Python — W1 (CLI half), W4, W5, W6, W7, W8** — can be written
  and tested here on Linux, including the full corruption battery,
  because none of it needs the engine.
- **All C++ — W2, W3 (commandlet half), W1 (replay)** — can be written
  here but **cannot be compiled or run** without a Windows box with
  UE 5.5 and the bridge built. Same honest boundary Phase 1 recorded.
  Every C++ change lands with the exact `build_ue.ps1` +
  `capture_windows.ps1` sequence needed to verify it, and nothing
  claims to be verified until that has been run.

## Suggested order

W5 first — it is pure Python, it is where the phase's credibility
actually lives, and it makes every later package checkable. Then W1 and
W2 together (they are the same seam). Then W3, W4, W6, W7, W8.

Doing W5 first also means the moment W2 lands on a Windows machine,
there is already a test standing by that can tell whether the pixels
and the labels agree.
