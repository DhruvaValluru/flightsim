# Phase 7 brief — real surface imagery, coupled terrain, richer atmosphere

Authorized by the owner on 2026-08-07. **Execution mode: autonomous, end to
end — do NOT pause for per-stage approvals.** Stop only when something
genuinely cannot be done headlessly on this machine (asset needs a login,
dataset offline, editor GUI required); then say exactly what is needed and
continue with everything else in the meantime.

Read `NEXT.md` first: it carries the resume state, the verification loop,
and the operational gotchas that cost hours to rediscover. Phase 6B's
guarantees are the floor — every gate, test and mutation guard stays green
after every increment, and every § honesty rule from the original brief
(measure or label; refuse rather than approximate; one lookup, verified
after load) applies to everything below.

## Step 0 — finish the Phase 6B deliverable if it is not finished

If `runs/showcase/showcase_manifest.json` is missing or lists fewer than 144
clips, run `.venv/bin/python experiments/showcase_matrix.py` (it resumes:
finished cells are kept, missing cells — including the 12 microburst cells —
are rendered, the contact sheet and manifest are rebuilt). Deliver the clips
and contact sheet to the owner.

## Tier 1 — biggest wins

### 1.1 Real surface imagery on the real terrain
- Drape true-colour satellite imagery over the georeferenced terrain meshes,
  replacing the approximated slope/altitude vertex classification for the
  two real locations. Source: Sentinel-2 cloudless / EOX or an equivalently
  licensed, headlessly fetchable dataset. Record license, tile IDs and
  sha256 in the bake sidecar and every render manifest, exactly as GLO-30 is
  recorded (core/terrain/glo30.py is the pattern).
- Pipeline: fetch → mosaic → crop to the SAME bbox as the DEM bake →
  reproject to the DEM's CRS so texel (u,v) aligns with the heightfield
  pixel grid → bake alongside the .r16 with its own sidecar + sha. The UE
  side imports the texture at build time (scripts/ue_import_aircraft.py is
  the import pattern; a M_TerrainImagery material with a texture parameter
  is the material pattern — scripts/ue_create_materials.py).
- Verify alignment, don't assume it: render a still over a summit whose
  image pixel is identifiable (e.g. the Matterhorn's shadowed north face)
  and CHECK the drape lands on the geometry (landmark projection through
  the camera of record, as Gate 6 does). Resolution and acquisition-date
  limits go in VALIDITY.md; the classification path stays for the control
  ridge and as fallback, still labeled approximated.

### 1.2 Terrain collision + AGL parity (the deferred stretch goal)
- Give the UE host real heightfield collision: the ground-query slab is
  replaced (for real-terrain cards) by collision built from the SAME baked
  raster the visuals draw — one raster, one sha, both uses.
- Give the headless host the matching ground: core/terrain/ground.py's
  TerrainGround already writes terrain elevation under the aircraft; wire it
  into the runner for terrain-carrying specs.
- MEASURE AGL parity over the real ridge: same spec, both hosts, compare
  h-agl on the recorded clock under Gate 5 discipline (tolerances stated
  before measuring; the comparison harness is experiments/gate5_ue_parity.py
  compare()). If parity holds, the "physics ground: flat slab" label comes
  OFF the affected clips and VALIDITY.md says what replaced it. If it does
  not hold, measure why, keep the label, publish the numbers.
- The commandlet's VerifyTrimmedCondition AGL check must be updated
  knowingly (it currently expects the flat slab) — an aircraft trimmed at
  300 m AGL over rising terrain is a different initial condition than over
  a slab, and the check must verify the RIGHT claim, not be loosened.

### 1.3 Rotor turbulence in the lee (measure first)
- The orographic provider computes lee-sink regions; the repo explicitly
  documents rotor turbulence there as not-modelled. Extension: couple
  Dryden severity to the lee zones.
- MEASURE FIRST on the pinned JSBSim build: does re-writing
  atmosphere/turbulence/milspec/severity and W20 per step (seed written
  once, never re-written — the 0.40 g → 515 g re-seed failure is
  docs/JSBSIM_CORRECTIONS territory) produce sane, continuous turbulence
  whose windowed RMS tracks the commanded severity? Write the measurement
  into docs/JSBSIM_CORRECTIONS.md whichever way it comes out.
- Only if the measurement passes: severity follows the lee-sink magnitude
  at the aircraft's position (C++ mirror + Python provider, cross-checked
  like FlightSimOrographic), null-tested (n_z RMS higher in the lee than on
  the windward side, same seed), mutation-guarded. If the measurement
  fails, document and stop — no schedule hacks.

## Tier 2 — more environment providers

Every provider follows the established pattern: Python provider with
citations + vocabulary + provenance in core/environment/, unit tests
(including a conservation/shape check where the physics offers one),
delivery to the UE host either as exact per-step schedule floats (pure
functions of time) or as a cross-checked C++ port (position-dependent
fields), a null test proving the effect reaches the FDM, a mutation guard,
and honest labels in card/manifest/panel.

### 2.1 Boundary-layer wind shear
- Log-profile wind below ~300 m AGL (u(z) = u* /k · ln(z/z0), stated
  roughness length per terrain class, cited). Position-dependent (altitude)
  → C++ port + selftest, like orographic. Matters exactly in the microburst
  regime; compose them.

### 2.2 Thermals
- Allen's convective thermal model (NASA/TM-2006-214019 — the soaring
  updraft model): thermal columns with stated radius/strength/spacing,
  deterministic placement from the spec seed. Position-dependent → C++
  port + selftest + null test (a glider-style c172p pass gains measurable
  n_z / climb events crossing columns). Summer-Yosemite cell.

### 2.3 Position-coupled microburst
- Port core/environment/downburst.py into the UE host (FlightSimOrographic
  is the exact pattern: constants mirrored, selftest grid in the manifest,
  Python recomputes and compares). Then the microburst cells couple to the
  aircraft's ACTUAL position and the "evaluated on the NOMINAL track" label
  comes off — replaced by the selftest evidence.

### 2.4 Von Kármán turbulence (optional, rank last)
- The certification-preferred spectrum; JSBSim ships only Dryden. An honest
  implementation needs the filter at FDM rate inside the step loop of BOTH
  hosts, which is a real numerical project (state-space filter, verified
  PSD against the analytic spectrum). Do not fake it with harness-rate
  noise; if not attempted, it stays listed as not-modelled.

## Tier 3 — flight and presentation

### 3.1 The evolving-conditions long flight
- One continuous 150 s clip: calm dawn → wind builds → gusts → storm with
  severe turbulence, sun rising through the flight, panel narrating
  plan-vs-actual with phase labels, and the phases VERIFIED from the
  recording afterward (windowed n_z RMS rising, FDM wind tracking the
  schedule).
- The machinery was designed and deliberately reverted mid-Phase-6B (card
  fields turbulence_schedule / orographic follow_schedule, sun-animation
  flags). Re-implement it COMPLETELY: a schedule field that parses but is
  not applied is a silent lie, so ReadCard support, Step() application
  (severity/W20 only — the seed is written exactly once), null checks and
  tests land in one increment or not at all.

### 3.2 More airframes
- The pipeline is generic: assets/aircraft_config/<name>.json → clone the
  GPL FlightGear model (record commit) → assets_pipeline/convert.py →
  scripts/ue_import_aircraft.py → experiments/gate5_realmesh.py must pass.
  Best exact matches: A320 (FDM names itself A320-200), DHC6, p51d. §1.4:
  the FDM named in the mesh manifest must be the FDM flown, enforced
  already — do not weaken it for a pretty mesh.

### 3.3 Flight paths, propellers, cameras
- Scripted banked waypoint paths (a valley run at Zermatt) via the existing
  control_inputs mechanism — scripted, reproducible, no autopilot claims.
- Propeller rotation bound to engine RPM through UFlightSimSurfaceAnimator
  (it is just another property→rotation binding; the c172p mesh has
  Propeller/Spinner objects, currently static and noted in VALIDITY.md).
- Additional camera presets (wing, tower, cockpit-shoulder) on the existing
  director; every preset keeps the §1.5 rule — the camera never inherits
  roll unless the preset SAYS it does, and the manifest records which.

### 3.4 Same-seed turbulence parity (investigation)
- Measured verdict today: both hosts are bit-repeatable alone, but consume
  the shared C-library generator from different stream positions, so
  same-seed realisations differ (runs/turbulence_ue/report.json). Options:
  vendored patch giving JSBSim turbulence an isolated, seed-owned RNG in
  BOTH hosts (pin + patch via scripts/vendor_ue_plugin.sh + VENDORED.json,
  re-asserted by check_bridge_api.sh), or document as permanently
  visual-only. Either outcome is fine; an unmeasured claim is not.

## Honesty requirements (unchanged, non-negotiable)
- Every visual claim measured or listed as not-established in VALIDITY.md;
  every new guard mutation-checked (scripts/mutation_check.sh); anything
  unimplementable headlessly reported, never substituted quietly.
- Keep the verification loop green after every increment: .venv/bin/pytest
  (261 at handoff), scripts/mutation_check.sh (49 guards), the gate
  scripts, experiments/gate5_realmesh.py, experiments/turbulence_ue.py
  --skip-runs, experiments/orographic_ue.py --skip-renders.
- Commit per increment with the evidence in the message.
