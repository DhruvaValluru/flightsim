**Phase 1 — Camera Control and Capture Geometry**

*Implementation plan for immediate work. Supersedes the phase summary in
the project plan.*

**Goal.** Promote the camera from a fixed render-time preset to a
first-class, attributed, validated element of the scenario
specification, and make every captured frame carry enough geometry to be
used as labeled data. A run should emit a defined number of images
rather than a clip, and two runs of the same specification with
different cameras should produce frame sets that align exactly in time.

**Deliverable.** Working software the instructor can run and verify
directly, plus a short document stating what was implemented, how to run
it, and what remains. Feature completeness is not required;
demonstrable, checkable capability is.

**Design decisions that shape the work**

**1. Camera poses are computed in Python and consumed verbatim by the
engine.** This mirrors the pattern the codebase already uses for wind
schedules, orographic forcing, and the tornado vortex: every parameter
is computed once on the Python side and applied without reinterpretation
by the C++ host. Applying it to cameras means the pose track exists
before rendering, the manifest can be written on any platform, and the
rendered frames cannot disagree with the recorded geometry, because both
come from the same array.

**2. The demonstration must not require macOS.** Rendering is macOS-only
and will remain so this phase. Because poses are solved in Python, the
camera specification, validation, scheduling, manifest, and all geometry
verification run on Windows and Linux. A lightweight geometry preview —
terrain and aircraft projected through the recorded camera matrix, drawn
without the engine — gives the instructor something visible and
checkable on any machine.

**3. Cameras reuse the existing attribution machinery rather than a
parallel one.** Each camera field is a provenanced Quantity like every
other field, so camera values appear in the review table with their
source, may be edited by hand, and are refused by named constraint when
invalid. Nothing about the camera should be an exception to the rule the
rest of the system follows.

**4. The specification schema gains a repeated block for the first
time.** The specification is currently a flat set of scalar fields.
Cameras are a list, which touches serialization, digest, table
rendering, and the language-model response schema. This is the single
largest structural risk in the phase and is scheduled first, with the
version bumped from 5 to 6 so that older specifications refuse by name
rather than being silently misread.

**Work package A — Camera specification and schema**

☐ Add a CameraSpec record whose fields are provenanced quantities:
identifier, preset or explicit placement, position or offset, aim mode
and target, lens focal length and sensor size or field of view, output
resolution, and near and far planes.

☐ Add a camera list to the scenario specification, extending canonical
serialization, YAML round-trip, and the digest so two specifications
differing only in cameras hash differently.

☐ Extend the review table to render each camera as its own labeled block
with per-field sources.

☐ Bump the specification version to 6 and confirm a version-5 document
refuses with a named error rather than loading partially.

☐ Provide documented camera defaults so that a specification with no
camera stated behaves exactly as the current build does.

**Work package B — Deterministic pose solver**

☐ Implement a pure function mapping recorded flight state and a camera
specification to a per-sample pose: world position, orientation, and the
full intrinsic set.

☐ Port the five existing presets — lagged chase, ground observer,
wingman, tower, cockpit shoulder — preserving the property that only the
cockpit view inherits aircraft roll, and preserving the recorded flag
that says so.

☐ Support explicit placement in scene coordinates and in geographic
coordinates, resolved against the scene's projection.

☐ Implement time-keyed moves: keyframes over position, aim, and focal
length, with deterministic interpolation and no dependence on frame rate
or wall-clock time.

☐ Solve poses over the telemetry produced by the headless runner, so a
pose track exists with no engine present.

☐ Add a regression test that the solver is bit-identical across repeated
invocations and across sample-rate changes that do not alter keyframe
times.

**Work package C — Capture scheduling**

☐ Implement fixed-interval triggers expressed either as a period or as
an exact image count over the run duration.

☐ Implement waypoint triggers: capture at defined points along the flown
track, by distance or by proximity to a coordinate.

☐ Implement event triggers over telemetry channels already recorded,
such as bank angle, load factor, or terrain proximity, with a documented
refractory period so one event does not produce a burst.

☐ Guarantee the emitted image count exactly matches the request, or
refuse before running with the reason.

☐ Make trigger evaluation a function of the telemetry record rather than
of render timing, so the schedule is identical whether or not frames are
rendered.

**Work package D — Validation and refusal**

☐ camera.terrain_clearance — refuse a pose that falls below the terrain
raster or within a minimum clearance of it, checked along the whole pose
track rather than at the first frame only.

☐ camera.scene_bounds — refuse a pose outside the baked scene extent,
where terrain and imagery do not exist.

☐ camera.hazard_intersection — refuse a pose inside a modeled hazard
volume, reusing the tornado core radius already computed for the vortex.

☐ camera.intrinsics — refuse non-physical lens or sensor values and
unsupported resolutions.

☐ camera.schedule — refuse triggers outside the run window, negative
counts, or a count unreachable at the run duration and rate.

☐ Confirm that a camera field stated by the user is never silently
moved, matching the rule applied to every other stated field.

☐ Add the camera constraints to the existing refusal surface so they
appear in the web interface exactly as the current refusals do.

**Work package E — Capture manifest**

The manifest is the deliverable that makes imagery usable. Written for
every run, on every platform, whether or not pixels were produced.

☐ Per frame: index, simulation time, camera identifier, image filename,
camera world position, orientation as quaternion and as Euler angles,
and the full intrinsic set including principal point and resolution.

☐ Per frame: the projection matrix, or the parameters from which it is
exactly reconstructible.

☐ Per frame: aircraft position and attitude at that instant, and the
geographic reference frame in which all positions are expressed.

☐ Per run: specification digest, telemetry digest, random seed, scene
identifier, terrain raster digest, and the software version.

☐ A documented schema, versioned, so downstream consumers can validate
before parsing.

☐ Keep the existing render manifest fields intact and additive, so
current gate scripts continue to pass.

**Work package F — Prompt surface**

☐ Extend the deterministic vocabulary with camera terms: named views,
counts, lens descriptions, and simple move phrases.

☐ Extend the model response schema so camera fields are extracted with
attribution, and are refused or overridden by the same downstream path
as any other model-supplied value.

☐ Add a clarifying question for camera intent when the prompt implies
imagery but names no viewpoint.

☐ Extend the prompt corpus check so camera extraction is measured rather
than assumed.

**Work package G — Engine consumption (macOS)**

☐ Carry the solved pose track on the run card, alongside the existing
precomputed blocks.

☐ Make the camera director consume poses per frame rather than computing
them, and refuse when the track does not cover the run.

☐ Render one pass per camera from the same specification, writing frames
into per-camera directories.

☐ Have the commandlet emit the same manifest fields as the headless
path, and fail loudly on any disagreement between solved and applied
pose beyond a stated tolerance.

☐ Reuse the existing world-to-pixel projection helper to verify
projected geometry against rendered frames.

**Work package H — Verification, and how the exit criterion is proven**

Each item below is a test the instructor can run and watch pass or fail.
The exit criterion is met when the first three hold.

☐ Temporal alignment: the same specification run twice with different
camera sets yields identical specification and telemetry digests,
identical frame counts, and per-frame simulation times equal to
floating-point tolerance.

☐ Geometry recovery: an independent projection implementation in the
test, not the producer, reprojects known world points through the
recorded pose and intrinsics and lands within a stated pixel tolerance
of the producer's own result.

☐ Cross-view consistency: a single world point visible from two cameras
at the same instant triangulates back to its known position within
tolerance, which is the practical statement of recoverable geometry.

☐ Refusal coverage: each named camera constraint has a test that trips
it and confirms the refusal rather than a run.

☐ Count exactness: a request for a specific number of images produces
exactly that number, across interval, waypoint, and event triggers.

☐ Mutation guards: disable each new safeguard in turn and confirm the
corresponding test fails, matching the existing convention.

☐ Engine parity, macOS only: rendered frames agree with the solved
manifest within tolerance, verified by projecting the aircraft position
into the frame.

**Work package I — Demonstration and documentation**

☐ A geometry preview renderer that draws terrain and aircraft through
the recorded camera matrix without the engine, so the capability is
visible on any platform.

☐ Two or three example specifications committed to the repository: a
multi-camera fixed-interval capture, a waypoint capture over real
terrain, and a refusal case with a camera placed inside a mountain.

☐ A single verification command that runs the alignment, recovery, and
consistency checks and prints a pass or fail summary.

☐ A short document stating what was implemented, what was not, how to
run each demonstration, expected output, and known limitations,
including the macOS rendering boundary.

**What the instructor will run**

Planned commands, on any supported platform. No account or key is
required.

> git clone \[repo\] && cd flightsim && ./scripts/setup.sh
>
> .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml
> --out runs/demo
>
> .venv/bin/python -m flightsim.verify runs/demo \# alignment, recovery,
> consistency
>
> .venv/bin/python -m pytest tests/test_camera\_\*.py -q
>
> .venv/bin/uvicorn webapp.server:app --port 8008 \# prompt, review
> table, run

Expected result off macOS: a manifest, a geometry preview image set, and
a passing verification summary, with rendered photographic frames
refused by name. On macOS the same commands additionally produce
rendered frames per camera.

**Scope boundaries for this phase**

Explicitly out of scope, to keep the deliverable achievable:
segmentation masks and bounding boxes, which depend on this phase and
belong to the next; domain randomization and batch execution; any
improvement to ground materials, vegetation, or weather visuals; the
agent controller; and porting rendering off macOS. Camera moves are
limited to keyframed placement, aim, and focal length — no physically
simulated camera platforms.

**Risks specific to this phase**

**Schema change breadth.** Adding a repeated block touches
serialization, digest, table rendering, the model schema, and the run
card at once. Scheduling package A first and keeping camera defaults
behaviorally identical to the current build limits the blast radius.

**Solved-versus-applied divergence.** If the engine ever recomputes a
pose instead of consuming it, the manifest becomes a plausible fiction.
The parity check in package G exists specifically to make that failure
loud.

**Verification that cannot fail.** A reprojection test written against
the producer's own code proves nothing. The independent implementation
requirement in package H is not a formality and should be reviewed as
such.

**Platform split in the demonstration.** The instructor's machine is
unknown. The Python-side pose solve and preview renderer are what make
the demonstration platform-independent, which is why they are in scope
rather than deferred.
