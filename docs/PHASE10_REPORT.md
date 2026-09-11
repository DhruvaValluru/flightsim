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
