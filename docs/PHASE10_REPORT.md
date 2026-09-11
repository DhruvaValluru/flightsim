# Phase 10 -- labeled multi-camera imagery: report

One report, a section per package, in the order the packages landed.
Each section says what was built, how to demonstrate it on any
platform, what was NOT verified in this environment, and the known
limitations -- the CAMERA_PHASE1_REPORT.md form. Scope was cut by the
owner on 2026-09-11 to what changes the simulation or the data that
comes out of it: packages 2, 3, 4, 7 and 6 (in that order), plus the
one piece of package 1 that meets that bar. Packages 5 (Linux), 8
(scene content), 9 (offline), 10 (signing/SBOM), 11 (sim-to-real),
12 (closed loop) and the VV&A document rewrite (1) are out by the
owner's decision, not silently missing.

Two numbers in the brief are already taken and are resolved here
rather than quietly: labels land at `manifest_version` **5** (3 added
`solve_source`, 4 the recorded row per frame), and the spec's one bump
this phase is 6 -> **7**, at the first field the phase adds.

## P10-2a -- the four terrain-coupling guards fire on every machine

**What was built.** The four terrain-coupled planner safeguards --
cross-ridge wind planning, the lee-rotor card word, the span-station
clearance minimum, the orographic pre-flight -- had tests that skipped
on any clone without a baked raster, so on CI and every fresh machine
their mutation guards reported WEAK: the safeguards were real, but
unverifiable. Now:

* `webapp.runs.TERRAIN_DIR` is the one name the scene picker, the
  fail-safe and the render flow read for baked terrain, so a test can
  point them at a synthetic bake without moving `REPO` out from under
  the asset and engine paths.
* `tests/test_webapp.py::control_ridge_root` synthesises a bake once
  per session (3-4 s). It is the SAME synthesis as the real control
  ridge (seed 6, 28 deg RMS slope, base 600 m) at 128 px, shaped by
  three measured needs and recorded in the raster's own provenance:
  a window centred one posting west of its peak (so the flight starts
  on the flank and the northbound track crosses ground above 2700 m;
  ON the peak, every span station sat over lower ground than the CG
  and the span-aware clause could not be strictly tighter -- measured);
  re-posted to span the real ridge's 30.7 km (the orographic field's
  wavelength is raster width / 8 and its decay height follows -- a
  3 km fixture put the field at cruise altitude at exactly 0.0 m/s,
  measured); elevations rescaled onto the real ridge's measured span
  (600 - 3299 m; the real ridge was generated once to measure it:
  247 s at 1024 px).
* Nine tests that skipped now run everywhere; `baked()` makes a
  half-written bake (samples without the sidecar) count as unbaked
  instead of crashing every terrain spec (found by this work -- see
  NEXT.md gotcha 27).
* Two path-traversal guards (image and clip routes) that had been WEAK
  for an unrelated reason -- one mutation target matching two lines,
  and no request able to reach the check -- now have unique targets
  and the one test that reaches them: a symlink planted inside the
  run directory (gotcha 28).

**How to demonstrate (any platform, no bakes needed).**

    .venv/bin/pytest tests/test_webapp.py -k "control_ridge or terrain or rotor or orographic or clearance"
    ./scripts/mutation_check.sh      # the five formerly-WEAK guards report ok

Measured on this Linux clone with no runs/terrain bakes: all five
guards fire (four terrain, one traversal) plus the new clip-traversal
and half-bake guards.

**Not verified here.** Nothing in this package touches the engine.

**Limitations.** The fixture is a 35 px re-posting at ~878 m: it makes
the PLANNERS' guards fire and says nothing about the real ridge's
slopes or the field's magnitudes there. The real 1024 px ridge stays
the render path's fail-safe, unchanged.

## P10-2 -- ground-truth labels per frame

**What was built.** Every frame record in a `manifest_version` 5
manifest carries a `labels` block computed from geometry alone, on
every machine, from the same record that placed the camera plus a
cited airframe:

* **The airframe** (`core/capture/airframe.py`). Definitions live in
  `assets/aircraft_config/<name>.json` under `labels`; the numbers are
  resolved from the pinned JSBSim model's own XML wherever it has them
  -- gear from `<contact>` elements, wingtips from the c172p's and
  A320's structural tip contacts, nose and tail from the A320's
  `NOSE_TIP`/`TAIL_TIP` and the c172p's skids -- and copied from a
  cited document only where it does not: the B747's nose and tail are
  placed by an argument from Boeing D6-58326-1 and carry `basis:
  estimate` in the manifest; its wingtips are half the FDM `<wingspan>`
  abeam the aero reference point, `basis: fdm-approximation` (sweep and
  dihedral not modelled -- stated). Heights come from the type
  documents (D6-58326-1, Airbus A320 ACAP, TCDS 3A12), spans from the
  flown FDM. JSBSim's structural frame (inches, x aft, z up, an
  author-chosen origin) is mapped to the labels' body frame (metres
  about the CG, x forward, z down -- the point the telemetry describes
  and the engine places the mesh by). The mapping is pinned by three
  numbers from nowhere near the code: the c172p's tips at +-5.46 m of
  a 10.91 m span, the A320's at +-16.96 m of 33.92 m, and the A320's
  nose-to-tail 37.5 m against the type's 37.57 m. An airframe with no
  stated geometry (DHC6, p51d, 737, global5000) refuses by name,
  `camera.labels`; so does a keypoint naming a contact the FDM lacks,
  or a stated point with no source.
* **The labels** (`core/capture/labels.py`): `bbox_2d` (the overall-
  extents box -- nose-to-tail x span x cited height from the gear
  contacts up -- projected and clipped) and `bbox_2d_unclipped`,
  `truncation`, `in_frame`, the 3-D box in camera coordinates (centre,
  extents, the body axes as rows, the eight corners in a documented
  order), every keypoint's pixel, depth and camera position with an
  `in_frame` that means in the image -- NOT unoccluded, stated -- and
  the horizon. The horizon is the datum plane's tangent horizon on a
  spherical Earth (IUGG mean radius, no refraction, no terrain), solved
  EXACTLY per image column: the image of a constant-depression cone is
  a conic, not a line, and the first version's chord through two far
  points sat 42 px low -- caught by the hand-arithmetic test. The
  label carries the exact polyline, a least-squares line, and the
  line's worst deviation from the curve (2.7 px across a 54 deg lens at
  1 km; it grows as sqrt(altitude)).
* **The manifest** carries `airframe` (every number with its source and
  basis, the config and FDM XML SHA-256), `label_conventions`, and
  `assets` (SHA-256 of the aircraft config, the FDM XML, the mesh
  manifest where one is imported -- null with a reason where not --
  and the imagery sidecar). Versions 3 and 4 still read; their label
  checks report NOT RUN.
* **The verifier** gained five checks that can fail: `label_geometry`
  re-projects the airframe block through the aircraft state with the
  verifier's own projection (0.05 px); `keypoints_in_box`; and three
  against the engine's per-frame outputs -- `label_files` (every file a
  render pass declared exists), `mask_containment` (>= 95% of the
  engine's aircraft-mask pixels inside the label box), `depth_range`
  (>= 99% of aircraft-mask depths within the 3-D box's span +- 2 m) --
  each NOT RUN without them. Each is shown to fail on a corrupted
  manifest or a fabricated inconsistent mask/depth
  (`tests/test_camera_labels.py`).
* **The engine half** (`FlightSimRenderCommandlet.cpp`, behind
  `-labels`, additive): per delivered frame, an instance mask
  (`frame_NNNN_mask.png`, aircraft = 1), a class mask (`_class.png`: 0
  sky, 1 aircraft, 2 terrain/other), 16-bit depth (`_depth.png`,
  metres = value x `depth_scale_m`, saturating at 6553.5 m), and an
  `occlusion_fraction` from two depth captures -- the aircraft alone
  and the full scene: a silhouette pixel is visible where the two
  depths agree. Declared per frame in that camera's `render.json`
  under `labels`, which is what the verifier reads. Without `-labels`
  the pass is byte-for-byte the previous one.

**How to demonstrate (any platform).**

    .venv/bin/pytest tests/test_camera_labels.py -q
    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/labels_demo
    .venv/bin/python -m flightsim.verify runs/labels_demo
    # every frame of capture_manifest.json (version 5) carries labels;
    # label_geometry and keypoints_in_box PASS; the three engine checks
    # report NOT RUN by name

On Windows, with the engine: add `-labels` to the render pass (the web
app and `flightsim.capture --render` pass it) and the three engine
checks run against the masks and depth.

**Not verified here.** The C++ was not compiled or run in this
environment (no engine). The Python verifier's engine checks are
exercised against fabricated masks and depth images of the declared
layout; whether the commandlet writes exactly that layout is the
Windows verification step: run one two-camera capture with `-labels`,
confirm `frames/<camera>/render.json` carries a `labels` object per
frame naming the three files, and that `label_files`,
`mask_containment` and `depth_range` come back PASS -- or fail, which
is a finding about the engine pass, not the labels.

**Limitations.** The 2-D box is the airframe's overall extents, not a
tight silhouette -- honest for what a machine without the mesh can
know, and the engine mask is the tight one. Keypoint `in_frame` is
geometric visibility only. B747 nose/tail are estimates and say so.
Semantic classes are three (sky / aircraft / terrain-or-other): water,
buildings and other aircraft are not distinguished -- scene content is
out of this phase's scope by the owner's decision. The horizon ignores
terrain occlusion; the engine mask is where the skyline is.

## P10-3 -- the sensor model (camera profiles)

**What was built.** A camera profile
(`assets/camera_profiles/<name>.json`) says what one camera does to an
ideal picture, and `core/capture/profile.py` applies it as a
deterministic, seeded post-pass in Python over the render, so the
result is reproducible from the run's provenance and checkable with no
engine. `CameraSpec` gained a provenanced `profile` field (the phase's
one spec bump, 6 -> 7; the examples were regenerated at 7, and a
version-6 dict refuses by name as every earlier bump did); the default
is `ideal_pinhole`, so a spec that names none behaves exactly as
before, and the ideal profile's post-pass is a no-op up to its own
8-bit ADC. An unknown profile, or one with no source, refuses by name
(`camera.profile`) in validation.

What a profile carries, and the stated basis of each part: Brown-Conrady
distortion (k1 k2 k3 p1 p2, the OpenCV parameterisation; forward for
the labels, Newton inverse for the image and the verifier -- round
trips to 1e-9); a linear top-to-bottom rolling shutter driven by the
camera's own angular rate from the solved pose track (translation over
one readout neglected, stated); cos^4 natural vignetting; exposure and
ISO as a gain over the profile's reference; EMVA 1288 shot + read noise
in electrons with the ADC at the profile's bit depth; linear in, sRGB
8-bit PNG out. The RNG is seeded per (run seed, camera, frame): the
same run writes the same bytes twice, a different seed different bytes
(tested).

Two profiles ship. `ideal_pinhole` is the documented default.
`synthetic_cmos_wide` is EXACTLY what its name and its source say: the
models are cited (Brown 1966; EMVA 1288; Ray's cos^4) and the numbers
are hand-chosen within the ranges those references describe -- not a
calibrated camera, and the profile's `basis: synthetic` and its source
string say so in the manifest. A calibrated profile for a real camera
replaces the numbers with measured ones and cites the calibration; the
loader refuses one that cites nothing.

**Labels follow the pixels.** Every frame record carries `sensor`:
the profile name, the camera's angular rate in camera axes, and
`labels_sensor` -- every keypoint and the 3-D box's corners mapped
onto the sensor (distortion, then the rolling-shutter row/time fixed
point). The camera block carries the profile's full parameters and
SHA-256. The verifier's `sensor_undistortion` undistorts and de-rolls
every sensor keypoint with the MANIFEST'S OWN recorded profile and
angular rate and requires the pinhole label back to 0.05 px; it is
shown to fail when the recorded k1 is corrupted, when the angular rate
is dropped, and when a frame names a different profile than its camera
block. `sensor_files` checks every sensor frame a camera's
`sensor.json` declares exists.

**Linear input.** The engine's colour capture is FinalColorLDR into an
sRGB8 target -- tone-mapped and quantised -- so the post-pass inverts
the sRGB transfer to get back to linear light and RECORDS that as a
stated approximation in `sensor.json`. An additive `-linear` option in
the commandlet captures FinalColorHDR into a float target and writes
`frame_NNNN_linear.exr` beside the PNG; the post-pass prefers it when
an EXR reader is installed (OpenEXR is not a dependency of this repo,
so on a stock machine the PNG path is what runs, and says so).

**How to demonstrate (any platform).**

    .venv/bin/pytest tests/test_camera_profile.py -q
    # in a spec: cameras[0].profile = synthetic_cmos_wide, then
    .venv/bin/python -m flightsim.capture <spec> --out runs/sensor_demo
    .venv/bin/python -m flightsim.verify runs/sensor_demo
    # sensor_undistortion PASS on the headless manifest; with rendered
    # frames, frames/<camera>/frame_NNNN_sensor.png beside each frame,
    # sensor.json naming the profile, the seed and the linear source

**Not verified here.** The `-linear` C++ was not compiled or run (no
engine). The post-pass over REAL rendered frames was exercised only on
synthetic stand-ins of the declared layout; the first Windows run with
a non-ideal profile is the verification step: `sensor_files` PASS and
a sensor frame that looks like a photograph of the ideal one (barrel,
fall-off, grain, and a skew under a fast pan).

**Limitations.** The synthetic profile is illustrative, by
construction. Rolling shutter neglects translation over one readout.
No chromatic aberration, no motion blur within the exposure, no
Bayer/demosaic, no lens flare -- each would be a further stated model.
Distorted output is sampled bilinearly from the ideal frame (no
supersampling), so a strong barrel lens softens edges slightly. The
sensor frame is 8-bit sRGB PNG regardless of the profile's bit depth,
which governs quantisation of the linear signal before encoding.
