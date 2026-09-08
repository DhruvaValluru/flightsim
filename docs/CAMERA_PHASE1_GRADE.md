# Camera Phase 1 — a hard grade, and what was fixed

An adversarial review of the Camera Phase 1 work as it stood at
`e73aee8`, graded against the phase document work package by work
package, followed by the repairs made on this branch. Everything below
was **measured on this tree**, not inferred from reading: the commands
that produced each number are given so the grade can be checked rather
than believed.

The short version: the phase's *engineering* was better than its
*evidence*. Nearly every box was ticked with real, careful code — and
the three checks the phase nominated as its own exit criterion could
not fail. A manifest with a camera displaced 500 m, a focal length
multiplied by 1.7, and 10 of 24 requested images passed all of them.
That is the exact failure the phase document warned about, in its own
words, and it had happened.

---

## Grade summary

| Package | Before | After | The deciding evidence |
|---|---|---|---|
| A — camera spec and schema | **A−** | A− | Genuinely done. Provenanced quantities, canonical serialization, digest, review table, version 6 refusal, documented defaults pinned byte-identical. One gap: no `camera.identifier` constraint (below). |
| B — deterministic pose solver | **B+** | B+ | Five presets ported faithfully, roll inheritance declared, keyframes deterministic. The claimed sample-rate independence holds only for keyframed `explicit` cameras; the lagged presets disagree by **1.68 m** between 10 Hz and 20 Hz. Documented now, not claimed away. |
| C — capture scheduling | **C+** | A− | Interval, distance and event triggers work and the count contract is real. But the **proximity trigger was unreachable from a specification** — implemented, documented, tested, and refused by the validator as an unknown trigger. Fixed. |
| D — validation and refusal | **B** | A− | Five named constraints, all riding the existing surface. Missing the sixth the schema needs: `camera_id` flowed unvalidated into filesystem paths. Fixed. |
| E — capture manifest | **A−** | A− | Complete, versioned, documented, additive. The one real weakness was that nothing ever checked it against anything. |
| F — prompt surface | **D+** | D+ | Named views, counts and lens words work. **Multi-camera prompts, move phrases, and every waypoint/event trigger word are absent.** Not fixed here — flagged with reproductions. |
| G — engine consumption | **D** | B− | The pose track is consumed verbatim; the **intrinsics were not**. `Capture->FOVAngle` was hardcoded at 55°/24° and the resolution at 1280×720 while the manifest recorded the spec's own lens. Fixed, plus orientation parity. Still uncompiled (no macOS here). |
| H — verification | **F** | A− | The headline finding. Three of the four checks could not fail; the fourth compared the delivery to itself. Four external-anchor checks added; every corruption now trips. |
| I — demonstration and docs | **C** | A− | Examples ran on a **flat** scene, so "over real terrain" and "inside a mountain" were neither. No single verification command existed (alignment needs two runs). Both fixed. |

**Overall: C+ → A−.** The C+ is not a comment on the code's quality. It
is a comment on a phase whose stated exit criterion was three
verification checks, where all three passed on a manifest that was
wrong.

---

## The headline finding: verification that could not fail

The phase document names this risk itself:

> *Verification that cannot fail. A reprojection test written against the
> producer's own code proves nothing. The independent implementation
> requirement in package H is not a formality and should be reviewed as
> such.*

`core/capture/verify.py` did implement its projection independently —
that part was done honestly. But independence of *code* buys nothing
when the only *data* the checks see is the producer's own
self-consistent output. Every check read the manifest against itself.

Measured on `runs/demo` (two cameras, 48 frames, produced by the
committed example), before any change:

| corruption | `geometry_recovery` | `cross_view_consistency` | `count_exactness` |
|---|---|---|---|
| camera displaced 500 m N, 300 m W, re-aimed | **PASS** | **PASS** | PASS |
| focal length × 1.7 on one camera | **PASS** | **PASS** | PASS |
| 10 of 24 requested images delivered, "10" written down | PASS | PASS | **PASS** |

The triangulation check deserves particular attention, because its
docstring explicitly claims to have avoided circularity. It casts each
camera's ray through the pixel that *that camera's own record* projected
its *own recorded aircraft position* to. Both rays therefore pass
through that point by construction, whatever the poses say. What the
check actually measures is whether the two records agree about where the
aircraft was — which is worth measuring, and is not what "cross-view
consistency" claims.

`count_exactness` compared `len(frames)` against
`manifest["cameras"][i]["capture_count"]`, which *is* `len(schedule)`.
It compared the delivery to itself. The requested count was sitting one
level down in the same file, in the recorded spec, unread.

### What was added

Three checks that anchor the manifest to artefacts the camera code did
not author:

* **`intrinsics_match_spec`** — recomputes `fx_px`, `fy_px` and the
  principal point from the camera specification's own lens, sensor and
  resolution recorded in the manifest, and compares per frame. `fx` and
  `fy` are checked separately on purpose: written as one `or`, either
  half covers for the other and neither guard is load-bearing.
* **`placement_matches_spec`** — world-anchored cameras must sit
  *exactly* where the specification puts them (or where its keyframes
  interpolate to); offset cameras must sit within a stated lag envelope
  of the unlagged goal point, `2 × v × τ`, because a first-order lag
  tracking a ramp trails by exactly `v·τ`. Measured worst case on
  `runs/demo`: 0.30 of the bound.
* **`telemetry_agreement`** — every frame's simulation time and aircraft
  state must be the ones `telemetry.json` holds at the sample index the
  frame names. A run with no telemetry beside its manifest now reports
  a *failure*, not a pass: "cannot be verified" is not "verified".

Plus **`engine_parity`**, which grades a render manifest's
`camera_applied_*` fields against the solved manifest, including the
field of view — package G's claim, made checkable from Python on any
platform.

After the change, every corruption in the table fails:

```
displaced 500 m       FAIL  placement_matches_spec: ... sits 583.095 m from the scene placement
chase displaced 500 m FAIL  placement_matches_spec: ... past the 149.5 m lag envelope
fx/fy x1.7            FAIL  intrinsics_match_spec: ... does not follow from the specified lens
focal 85 mm           FAIL  intrinsics_match_spec: focal_length_mm is 85.0, the specification says 35.0
10 of 24 delivered    FAIL  count_exactness: 10 frames delivered against the 24 its specification requests
sample index shifted  FAIL  telemetry_agreement: ... telemetry sample 3 is at t=0.325000 s
sim time shifted      FAIL  telemetry_agreement: ... records t=0.058333 s where sample 0 is at t=0.008333 s
```

Thirteen mutation guards were added, each verified to fail its test when
its safeguard is disabled — including two that exposed *shadowing*: the
existing dense-index guard had become non-load-bearing once the
requested-count check was added, and the `fx`/`fy` pair covered for each
other. Both are now separately guarded with tests only one of them can
satisfy.

---

## The renderer described a camera the pixels were never taken with

`FlightSimRenderCommandlet.cpp:797`, before this branch:

```cpp
Capture->FOVAngle = bVisual ? 55.0f : 24.0f;
```

A hardcoded field of view, never derived from the camera specification.
The output resolution was equally fixed: `webapp/runs.py` passed
`-width=1280 -height=720` from `experiments/showcase_matrix`.
Meanwhile the capture manifest recorded, for every frame,
`fx_px = focal_mm / sensor_mm × width_px`.

The consequences, in the units that matter:

* **Default camera.** 35 mm on a 36 mm sensor is 54.43° horizontal.
  Rendered at 55.0°, `fx` is 1229.4 px against the manifest's 1244.4 px
  — a 1.2% scale error, which is **7.8 px at the frame edge**, fifteen
  times the phase's own 0.5 px reprojection tolerance.
* **A stated telephoto.** A user who asks for an 85 mm lens gets
  `fx = 3022 px` in the labels and 1229 px in the pixels — the recorded
  geometry is wrong **by a factor of 2.5**, and every bounding box or
  mask derived from it in a later phase would be wrong by the same
  factor.

Package G's parity check could not see it, because it compared position
only. Package H's engine-parity item — "verified by projecting the
aircraft position into the frame" — would have been nearly blind to it
too, since an aimed camera keeps the aircraft near the principal point,
where a focal-length error vanishes.

This is precisely the phase's second named risk ("the manifest becomes a
plausible fiction"), and the mechanism designed to catch it was pointed
at the wrong half of the pose.

### What was changed

* The commandlet now consumes `width_px`, `height_px`, `sensor_width_mm`
  and the per-sample `focal_length_mm` from the card's camera block, and
  sets `Capture->FOVAngle` from them per frame (so a keyframed focal
  length is honoured); it **refuses** a camera block that does not carry
  them rather than choosing a framing the manifest does not describe.
* `ApplyPoseAtTime` now checks **orientation** parity as well as
  position, at 0.05°.
* `render.json` gains `camera_applied_hfov_deg` / `_width_px` /
  `_height_px`, and `verify_engine_parity` grades them.
* `core/capture/manifest.py` gains `horizontal_fov_deg` and
  `pixel_focal_from_fov` — one statement of the lens, so the two halves
  cannot each carry their own.

**Not verified by execution.** There is no macOS and no engine in this
environment; the C++ changes are logically complete and follow the
plugin's own conventions, and they have not been compiled. The Python
half of the parity check is tested and fails on exactly the 55° defect.

---

## The proximity trigger was unreachable

`core/capture/schedule.py` implements a proximity trigger, documents it
in its module docstring, and `tests/test_camera_schedule.py` exercises
it. `core/capture/validate.py` has a branch for it. The phase document
asks for it by name: *"waypoint triggers: capture at defined points
along the flown track, by distance **or by proximity to a coordinate**."*

But `TRIGGER_KINDS` was `("interval", "distance", "event")`. Any
specification naming `proximity` was refused as an unknown trigger
before the scheduler was ever called:

```
[camera.schedule] camera[0] 'cam0': unknown trigger 'proximity';
                  modelled: interval, distance, event
```

The tests passed because they called `solve_schedule` directly, bypassing
the validator. This is the same species of problem as the verification
finding: a test that exercises a path no run can take.

Fixed by adding `proximity` to the vocabulary, with tests that go
through validation and a YAML round-trip rather than around them.

---

## `camera_id` was a filesystem injection

The camera id names a directory: the manifest's per-frame `file` is
`frames/<camera_id>/frame_00042.png`, and the preview renderer writes
`previews/<camera_id>/`. Nothing validated it.

Measured on this tree, a specification with `camera_id: ../../pwned`:

```
$ python -m flightsim.capture evil.yaml --out scratch/probe/run
captured: 48 frames across 2 camera(s)
$ find scratch/probe -name '*.png'
scratch/probe/pwned/preview_00000.png     <- outside the run directory
scratch/probe/pwned/preview_00001.png
```

On Windows the failure mode is worse and more likely to happen by
accident: `cam:0`, `cam?0`, a trailing dot or space, or any of `CON`,
`NUL`, `COM1` is an unrecoverable file-creation failure *halfway through
a run*, after the flight has been flown.

Fixed with a `camera.identifier` constraint that faces the strictest of
the three filesystems: letters, digits, `_`, `-`, `.`; no leading dot,
no trailing dot or space, no Windows reserved device stem, 64 characters.
Refused by name, never sanitised — a silently rewritten id would put the
frames somewhere the user did not ask for and label them by a name the
run never used. The web app's preview endpoint applies the same rail to
its URL segments.

---

## The web app produced nothing at all off macOS

This is the gap between what the phase promises and what an instructor
on Windows actually saw.

The phase document is explicit:

> *[The manifest is] written for every run, on every platform, whether or
> not pixels were produced.*
>
> *Expected result off macOS: a manifest, a geometry preview image set,
> and a passing verification summary, with rendered photographic frames
> refused by name.*

`webapp/server.py`'s `/run` returned `409 ue.platform` before the run
manager was ever reached, and `RunManager.start` refused again on the
same condition. On Windows or Linux, pressing **Run** produced: no
telemetry, no manifest, no previews, no verification. Nothing. The CLI
delivered the phase; the web app — which is on the instructor's own
command list — delivered a refusal.

### What was changed

The capture half now runs on every platform, and only the pixels are
refused:

* `webapp/runs.py` gains `capture_flow()`: headless flight → solved pose
  tracks → capture schedule → solved-track scene checks → capture
  manifest → geometry previews → verification, using the same
  `core/capture` code the CLI uses.
* `RunManager._execute` runs it first, then the render half only where
  the engine exists. The named render refusal (`ue.platform`, then
  `aircraft.mesh` — **that order is unchanged and still pinned**) is
  recorded on the run and returned as `render_refused` on the 200
  response, instead of replacing the run.
* New endpoints: `GET /runs/{id}/capture_manifest.json`,
  `GET /runs/{id}/verify` (re-runs the checks and returns the report),
  `GET /runs/{id}/previews/{camera}/{file}`.
* The page shows the capture summary, per-camera schedule bases, the
  verification checks by name, and a gallery of geometry previews; a
  run with no clip no longer renders an empty video player.
* A completed capture now survives a server restart (recovery required a
  `clip.mp4`, which off-mac never exists).

Measured on this Linux machine, through the real HTTP surface:

```
run status_code: 200   render_refused: ue.platform
final status: done | captured; pixels refused by name (ue.platform)
capture: 12 frames, 1 camera (cockpit), 12 previews
verify:  verification PASSED (8/8 checks)
manifest: 200, 18505 bytes
preview:  200 image/png
```

The two tests that pinned the old 409 behaviour were rewritten rather
than deleted: the *lesson* they encode (a machine with no engine hears
`ue.platform`, not `aircraft.mesh`) is now pinned on
`RunManager.render_refusal`, where the ordering lives, and the new
behaviour has its own end-to-end tests.

---

## The demonstration was not what it said it was

Package I asks for "a waypoint capture over real terrain" and "a refusal
case with a camera placed inside a mountain". Neither committed example
touched a raster:

* `cameras_waypoint.yaml` ran on a **flat** scene; its header offered
  `--terrain runs/terrain/matterhorn`, a bake a fresh clone does not
  have and cannot get without network and time.
* `cameras_refusal.yaml` refused against the spec's **flat datum**, not
  against terrain. There was no mountain.

And the "single verification command that runs the alignment, recovery,
and consistency checks" did not exist. `flightsim.verify` grades one run
directory, and temporal alignment is a statement about *two* runs of the
same simulation — it is structurally impossible to report from one.

### What was changed

* **`python -m flightsim.demo`** — the single command. Captures a
  specification, captures the same simulation again with a different
  camera set, verifies each, and reports the alignment between them in
  one pass/fail summary. `scripts/verify_phase1.sh` and
  `scripts/verify_phase1.ps1` wrap it with the camera test suite and the
  refusal example, one command per platform.
* **`--synth-terrain`** — synthesises a deterministic raster *centred on
  the spec's own origin* (the existing spectral-construction-plus-erosion
  pipeline; a raster the flight is not over is a flat datum with extra
  steps). No network, no account, bit-identical from its seed, and it
  reaches the ground callback as the same `Heightfield` a Copernicus
  bake produces.
* **`examples/cameras_terrain.yaml`** — a waypoint capture along the
  flown track plus a ridge-shoulder camera on an 85 mm telephoto taking
  exactly 20 images, over that raster. 30 frames, 8/8 checks.
* **`examples/cameras_mountain_refusal.yaml`** — a camera stated 545 m
  *inside* the ridge, refused `camera.terrain_clearance` against the
  raster before anything runs.
* A terrain impact or a trim failure in the capture CLI is now a named
  refusal instead of a stack trace (measured: flying the 1200 m waypoint
  example over a 3043 m ridge printed a traceback at the instructor).

---

## Findings not fixed on this branch

These are real and reproducible. They are documented rather than
repaired, because repairing them well is larger than this change.

### 1. The lagged presets are not sample-rate independent

Package B asks for a regression test that the solver is "bit-identical
across repeated invocations **and across sample-rate changes that do not
alter keyframe times**". The committed test
(`test_keyframes_agree_across_telemetry_rates`) covers only the
`explicit` preset with keyframed moves — where the solution really is a
continuous function being sampled.

The chase, wingman and tower presets use an exponential lag filter,
`alpha = 1 - exp(-dt/tau)`, driven by a *moving* goal. That recursion is
not rate-invariant. Measured, same flight, 10 Hz against 20 Hz, at
shared sample times:

| preset | worst position gap | worst yaw gap |
|---|---|---|
| chase | **1.679 m** | 0.065° |
| wingman | **1.676 m** | 0.042° |
| tower | 0.000 m | 0.086° |
| cockpit | 0.000 m | 0.000° |

On a harder track (a banked, climbing 140 m/s turn) the chase gap
reaches **3.29 m**; `tests/test_camera_poses.py` now measures both and
pins a bound per preset, and a companion test asserts the lagged presets
are *not* invariant, so the limitation cannot be silently claimed away
later.

Exact invariance is impossible in principle — the goal is only known at
sample times — but the current zero-order-hold discretisation is the
crudest available choice, and a ramp-exact (first-order-hold) form would
cut the error by roughly an order of magnitude. Changing it moves every
existing pose digest, so it is a deliberate follow-up, not a drive-by.
The report's claim of "cross-rate keyframe agreement" should be read as
scoped to keyframes, which is what the test actually shows.

### 2. The prompt surface is roughly one third of package F

Package F asks for "named views, counts, lens descriptions, and simple
move phrases". Measured against the deterministic compiler:

```
"chase and tower views ... 24 images each"      -> 1 camera  ['chase']
"capture every 400 m along the track"           -> no camera at all
"tower view panning from north to east over 20s"-> moves: []
```

* **Multi-camera prompts are not expressible.** `compile_prompt` builds
  at most one `CameraSpec`. The phase's own flagship demonstration —
  two cameras on one flight — cannot be asked for in words.
* **Move phrases are absent entirely.** There is no keyframe parsing in
  either compiler, and `moves` is not in the LLM response schema.
* **No trigger word reaches the spec.** `CAMERA_FIELD_VALUE_SCHEMAS`
  exposes `preset`, `focal_length_mm`, `capture_count` and `period_s`
  only, so waypoint and event capture — two thirds of package C — are
  unreachable from a prompt in either compiler.

The corpus check exists and passes; it measures what the vocabulary can
already express, which is the narrower claim.

### 3. Cross-view consistency remains partly self-referential

`placement_matches_spec` and `telemetry_agreement` now anchor the poses
and the aircraft states externally, which removes most of the freedom the
triangulation check had. But the triangulation itself still casts each
ray through a pixel that camera's own record produced. A genuinely
independent formulation would triangulate a point the *scene* provides
— a terrain summit, a runway threshold — rather than the subject the
cameras are aimed at. That is worth doing and is not done here.

### 4. Only the first two cameras of an instant are triangulated

`verify_triangulation` takes `records[0], records[1]` per shared sample
index. A three-camera capture verifies one of its three pairs.

### 5. Four mutation guards report WEAK on a raster-less clone

Pre-existing and already recorded in `NEXT.md`: the ridge-axis wind,
rotor card word, span-station clearance and orographic pre-flight guards
report WEAK on a machine with no baked terrain, because their tests
silently take the flat path. `core/terrain/synthesis.ridge_for_origin`,
added here, is exactly the fixture those tests need to become
machine-independent.

---

## How to check this grade

Every claim above is reproducible on any platform, with no account and
no key:

```bash
./scripts/setup.sh
./scripts/verify_phase1.sh                    # Windows: .\scripts\verify_phase1.ps1

# the specific findings
.venv/bin/pytest tests/test_camera_verify.py -q       # the corruptions that now fail
.venv/bin/pytest tests/test_camera_validate.py -q     # the identifier rail
.venv/bin/pytest tests/test_webapp.py -k capture -q   # the web app on this platform
.venv/bin/python -m flightsim.capture examples/cameras_mountain_refusal.yaml \
    --out runs/buried --synth-terrain                 # REFUSED [camera.terrain_clearance]

# the whole suite and every guard
.venv/bin/pytest -q                                   # 627 passed, 10 skipped (mac-gated)
./scripts/mutation_check.sh                           # 127 guards
```

State of the tree after this branch: **627 tests passing, 10 skipped
(macOS-gated, visibly), 127 mutation guards of which the 13 new ones
were each verified to fail their test when disabled.** The four WEAK
guards named in finding 5 are pre-existing and environment-dependent.
