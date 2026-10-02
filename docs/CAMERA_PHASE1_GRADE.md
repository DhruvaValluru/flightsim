# Camera Phase 1 — a hard grade, and what survived it

An adversarial review of Camera Phase 1 as it stood at **`e73aee8`**
(the `master` merge of the phase), graded work package by work package.
Everything below was **measured**, not inferred from reading: the
commands that produced each number are given so the grade can be checked
rather than believed.

**Read this with its history in mind.** The review was carried out on a
branch taken from `e73aee8`, in parallel with the Camera Phase 2 work on
*this* branch. The two did not know about each other. Most of the
serious findings below were reached independently by both and are
**already fixed here** — by the Phase 2 commits, usually more thoroughly
than the review's own repairs, which were dropped in favour of them. The
value of this document is therefore not "here is what I fixed" but:

* a record of what was actually wrong at `e73aee8`, with reproductions,
  so the phase's exit criterion is never again believed on assertion; and
* the findings that **survived** — the ones neither effort fixed, which
  are still open on this branch today.

The short version of the grade: the phase's *engineering* was better
than its *evidence*. Nearly every box was ticked with real, careful code
— and the three checks the phase nominated as its own exit criterion
could not fail. A manifest with a camera displaced 500 m, a focal length
multiplied by 1.7, and 10 of 24 requested images passed all of them.
That is the exact failure the phase document warned about, in its own
words, and it had happened.

---

## Grade summary

"Fixed by" names which effort closed it: **P2** = the Camera Phase 2
commits on this branch; **review** = the parallel review, ported here.

| Package | At `e73aee8` | Now | Fixed by | The deciding evidence |
|---|---|---|---|---|
| A — camera spec and schema | **A−** | A | review | Provenanced quantities, canonical serialization, digest, review table, version-6 refusal, defaults pinned byte-identical. One gap: no `camera.identifier` constraint — `camera_id` reached the filesystem unchecked. |
| B — deterministic pose solver | **B+** | B+ | — | Presets ported faithfully, roll inheritance declared, keyframes deterministic. The claimed sample-rate independence holds only for keyframed `explicit` cameras. **Still open** (finding 1); now measured and bounded by test rather than claimed away. |
| C — capture scheduling | **C+** | A− | review | The count contract is real. But the **proximity trigger was unreachable from a specification** — implemented, documented, tested, and refused by the validator as an unknown trigger. |
| D — validation and refusal | **B** | A− | review | Five named constraints, all riding the existing surface. Missing the sixth the schema needs (`camera.identifier`). |
| E — capture manifest | **A−** | A | P2 | Complete, versioned, documented, additive. Its one real weakness was that nothing checked it against anything; P2 added the landmarks that give it external truth. |
| F — prompt surface | **D+** | D+ | — | Named views, counts and lens words work. **Multi-camera prompts, move phrases, and every waypoint/event trigger word are absent.** **Still open** (finding 2); `core/nl/` is untouched by both efforts. |
| G — engine consumption | **D** | A− | P2 | The pose track was consumed verbatim; the **intrinsics were not**. `Capture->FOVAngle` was hardcoded at 55°/24° and the resolution at 1280×720 while the manifest recorded the spec's own lens. P2 fixed it, added orientation parity, and grades it against real rendered frames. |
| H — verification | **F** | A | P2 | The headline finding. Three of the four checks could not fail; the fourth compared the delivery to itself. P2 rebuilt the module around landmarks with known truth positions and the engine's own measured pixels. |
| I — demonstration and docs | **C** | A− | both | Examples ran on a **flat** scene, so "over real terrain" and "inside a mountain" were neither; no single verification command existed. P2 added the Windows capture path and its docs; the review added the terrain examples and the one command. |

**Overall at `e73aee8`: C+.** Not a comment on the code's quality — a
comment on a phase whose stated exit criterion was three verification
checks, where all three passed on a manifest that was wrong.

---

## Finding: verification that could not fail (fixed by P2)

The phase document names this risk itself:

> *Verification that cannot fail. A reprojection test written against the
> producer's own code proves nothing. The independent implementation
> requirement in package H is not a formality and should be reviewed as
> such.*

`core/capture/verify.py` at `e73aee8` did implement its projection
independently — that part was done honestly. But independence of *code*
buys nothing when the only *data* the checks see is the producer's own
self-consistent output. Every check read the manifest against itself.

Measured on `runs/demo` (two cameras, 48 frames, from the committed
example) at `e73aee8`:

| corruption | `geometry_recovery` | `cross_view_consistency` | `count_exactness` |
|---|---|---|---|
| camera displaced 500 m N, 300 m W, re-aimed | **PASS** | **PASS** | PASS |
| focal length × 1.7 on one camera | **PASS** | **PASS** | PASS |
| 10 of 24 requested images delivered, "10" written down | PASS | PASS | **PASS** |

The triangulation check deserved particular attention, because its
docstring claimed to have avoided circularity. It cast each camera's ray
through the pixel that *that camera's own record* projected its *own
recorded aircraft position* to. Both rays therefore passed through that
point by construction, whatever the poses said. What it actually
measured was whether the two records agreed about where the aircraft
was — worth measuring, and not what "cross-view consistency" claims.

`count_exactness` compared `len(frames)` against
`manifest["cameras"][i]["capture_count"]`, which *is* `len(schedule)`.
It compared the delivery to itself. The requested count sat one level
down in the same file, in the recorded spec, unread.

**How this branch fixes it.** P2 rebuilt the module around **static
landmarks with known world positions**, projected by this module and
independently *measured by the engine* in its own `render.json`:
`verify_landmark_reprojection` compares the two, and
`verify_triangulation` triangulates a landmark's truth position from two
cameras' sightings. `verify_intrinsics` recomputes `fx`/`fy` from the
recorded spec; `verify_pose_matches_spec` holds stated placements to
1e-6 m and bounds an aimed camera's forward axis; `verify_counts` reads
the count the **specification requested**; `verify_flight_agreement`
measures the manifest's aircraft track against the host's own telemetry.

That is a stronger answer than the review's own repair, which anchored
to the spec and the headless telemetry but still triangulated the
aircraft the cameras were aimed at. The review's versions were dropped.

---

## Finding: the renderer described a camera the pixels were never taken with (fixed by P2)

`FlightSimRenderCommandlet.cpp`, at `e73aee8`:

```cpp
Capture->FOVAngle = bVisual ? 55.0f : 24.0f;
```

A hardcoded field of view, never derived from the camera specification.
The output resolution was equally fixed at 1280×720. Meanwhile the
capture manifest recorded, for every frame,
`fx_px = focal_mm / sensor_mm × width_px`.

* **Default camera.** 35 mm on a 36 mm sensor is 54.43° horizontal.
  Rendered at 55.0°, `fx` is 1229.4 px against the manifest's 1244.4 px
  — **7.8 px of disagreement at the frame edge**, fifteen times the
  phase's own 0.5 px reprojection tolerance.
* **A stated telephoto.** 85 mm gives `fx = 3022 px` in the labels and
  1229 px in the pixels — the recorded geometry wrong **by a factor of
  2.5**, and every mask or box derived from it in a later phase wrong by
  the same factor.

Package G's parity check could not see it: it compared position only.
Package H's engine-parity item would have been nearly blind too, since
an aimed camera keeps the aircraft near the principal point, where a
focal-length error vanishes.

**How this branch fixes it.** P2 makes the commandlet consume the
camera's own intrinsics and adds orientation parity to
`ApplyPoseAtTime`, then grades applied-versus-solved against real
rendered frames (`tests/test_camera_engine_parity.py`).

---

## Findings this branch fixes from the review

Neither was touched by P2; both are ported here.

### `camera_id` was a filesystem injection

The camera id names a directory: the manifest's per-frame `file` is
`frames/<camera_id>/frame_00042.png`, and the preview renderer writes
`previews/<camera_id>/`. Nothing validated it.

Measured, with `camera_id: ../../pwned`:

```
$ python -m flightsim.capture evil.yaml --out scratch/probe/run
captured: 48 frames across 2 camera(s)
$ find scratch/probe -name '*.png'
scratch/probe/pwned/preview_00000.png     <- outside the run directory
scratch/probe/pwned/preview_00001.png
```

On Windows the failure mode is worse and more likely by accident:
`cam:0`, `cam?0`, a trailing dot or space, or any of `CON`, `NUL`,
`COM1` is an unrecoverable file-creation failure *halfway through a run*,
after the flight has been flown.

Now a `camera.identifier` constraint facing the strictest of the three
filesystems: letters, digits, `_`, `-`, `.`; no leading dot, no trailing
dot or space, no Windows reserved device stem, 64 characters. **Refused
by name, never sanitised** — silently rewriting a user's camera id would
put frames somewhere they did not ask for and label them by a name the
run never used.

### The proximity trigger was unreachable

`core/capture/schedule.py` implements a proximity trigger, documents it,
and `tests/test_camera_schedule.py` exercises it. The phase document
asks for it by name: *"waypoint triggers: capture at defined points
along the flown track, by distance **or by proximity to a
coordinate**."*

But `TRIGGER_KINDS` was `("interval", "distance", "event")`. Any
specification naming `proximity` was refused before the scheduler was
ever called:

```
[camera.schedule] camera[0] 'cam0': unknown trigger 'proximity';
                  modelled: interval, distance, event
```

The tests passed because they called `solve_schedule` directly, bypassing
the validator — the same species of problem as the verification finding:
a test exercising a path no run can take. Now in the vocabulary, with
tests that go **through** validation and a YAML round-trip.

### The demonstration was not what it said it was

Package I asks for "a waypoint capture over real terrain" and "a refusal
case with a camera placed inside a mountain". Neither committed example
touched a raster: `cameras_waypoint.yaml` ran on a **flat** scene, and
`cameras_refusal.yaml` refused against the spec's **flat datum**. There
was no mountain.

And the "single verification command that runs the alignment, recovery,
and consistency checks" did not exist — `flightsim.verify` grades one run
directory, and temporal alignment is a statement about *two* runs of the
same simulation, structurally impossible to report from one.

Added here:

* **`python -m flightsim.demo`** — the single command. Captures a
  specification, captures the same simulation again with a different
  camera set, verifies each, and reports the alignment between them in
  one pass/fail summary. `scripts/verify_phase1.sh` / `.ps1` wrap it with
  the camera suite and the refusal example.
* **`--synth-terrain`** — a deterministic raster *centred on the spec's
  own origin* (a raster the flight is not over is a flat datum with extra
  steps), from the existing spectral-construction-plus-erosion pipeline.
  No network, no account, bit-identical from its seed, and it reaches the
  ground callback as the same `Heightfield` a Copernicus bake produces.
* **`examples/cameras_terrain.yaml`** — waypoint capture along the flown
  track plus a ridge-shoulder camera on an 85 mm telephoto taking
  exactly 20 images, over that raster.
* **`examples/cameras_mountain_refusal.yaml`** — a camera stated 545 m
  *inside* the ridge, refused `camera.terrain_clearance` against the
  raster before anything runs.
* A terrain impact or trim failure in the capture CLI is now a **named
  refusal** instead of a stack trace (measured: flying the 1200 m
  waypoint example over a 3043 m ridge printed a traceback).

---

## Findings still open on this branch

Neither effort fixed these. They are real and reproducible today.

### 1. The lagged presets are not sample-rate independent

Package B asks for a regression test that the solver is bit-identical
"across sample-rate changes that do not alter keyframe times". The
committed test covers only the `explicit` preset with keyframed moves —
where the solution really is a continuous function being sampled.

Chase, wingman and tower use an exponential lag filter,
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
reaches **3.29 m**. `tests/test_camera_poses.py` now measures both and
pins a bound per preset, plus a companion test asserting the lagged
presets are *not* invariant — so the limitation cannot be silently
claimed away later.

Exact invariance is impossible in principle (the goal is only known at
sample times), but the current zero-order-hold discretisation is the
crudest available choice; a ramp-exact form would cut the error by
roughly an order of magnitude. Changing it moves every existing pose
digest, so it is a deliberate follow-up, not a drive-by.

### 2. The prompt surface is roughly one third of package F

Package F asks for "named views, counts, lens descriptions, and simple
move phrases". Measured against the deterministic compiler:

```
"chase and tower views ... 24 images each"       -> 1 camera  ['chase']
"capture every 400 m along the track"            -> no camera at all
"tower view panning from north to east over 20s" -> moves: []
```

* **Multi-camera prompts are not expressible.** `compile_prompt` builds
  at most one `CameraSpec`. The phase's own flagship demonstration —
  two cameras on one flight — cannot be asked for in words.
* **Move phrases are absent entirely.** No keyframe parsing in either
  compiler; `moves` is not in the LLM response schema.
* **No trigger word reaches the spec.** `CAMERA_FIELD_VALUE_SCHEMAS`
  exposes `preset`, `focal_length_mm`, `capture_count` and `period_s`
  only, so waypoint and event capture — two thirds of package C — are
  unreachable from a prompt in either compiler.

`core/nl/` is untouched by both efforts. The corpus check exists and
passes; it measures what the vocabulary can already express, which is
the narrower claim.

### 3. Triangulation still takes only the first two sightings

`verify_triangulation` groups sightings by `(sample_index, landmark)`
and then takes `seen[0], seen[1]`. With landmarks this is a far richer
set of pairs than the old per-instant aircraft pairing, so the practical
coverage is good — but a three-camera capture still verifies one pair
per landmark per instant rather than all of them.

---

## How to check this grade

Reproducible on any platform, with no account and no key:

```bash
./scripts/setup.sh
./scripts/verify_phase1.sh                    # Windows: .\scripts\verify_phase1.ps1

# the findings this branch fixes from the review
.venv/bin/pytest tests/test_camera_validate.py -q     # the identifier rail
.venv/bin/pytest tests/test_camera_schedule.py -q     # proximity, reachable
.venv/bin/pytest tests/test_camera_poses.py -q        # the rate-sensitivity bounds
.venv/bin/python -m flightsim.capture examples/cameras_mountain_refusal.yaml \
    --out runs/buried --synth-terrain                 # REFUSED [camera.terrain_clearance]

# everything
.venv/bin/pytest -q                                   # 659 passed, 10 skipped (mac-gated)
./scripts/mutation_check.sh                           # 127 guards
```
