# Phase 6B brief — real aircraft, real Earth terrain, turbulence, condition matrix

Authorized by the owner on 2026-08-06. **Execution mode: autonomous, end to
end, all sections in one continuous run — do NOT pause for per-stage approval.**
Stop only when something genuinely cannot be done headlessly on this machine
(asset needs a login, dataset offline, editor GUI required); then say exactly
what is needed and continue with everything else in the meantime.

Build Phase 6B on ~/flightsim: replace the placeholder visuals with a real
aircraft and REAL EARTH terrain from named locations, wire turbulence into
the Unreal host, and produce a condition matrix of rendered clips — while
keeping every research guarantee the repo already has.

## 1. Real aircraft mesh
- Acquire a properly-licensed 3D aircraft model with separate control-surface
  geometry (or bones): candidates are the Khronos glTF-Sample-Assets aircraft,
  NASA 3D Resources (public domain), or another source downloadable headlessly.
  Verify and record the license (§3.3) before using it. If the mesh's airframe
  doesn't match the flown FDM, REFUSE the pairing — §1.4 is the failure this
  repo exists to prevent. One mesh per airframe flown, or fly the airframe
  the mesh matches.
- Import at build time, fully command-line (UE Interchange / converter script).
- Bind control surfaces through the existing UFlightSimSurfaceAnimator.
  Re-run Gate 5's on-screen clauses against the real mesh (r >= 0.98 roll
  tracking, surfaces measurably articulate). Gate 5 must not regress.

## 2. Real Earth terrain — actual named mountains, as measured
- Locations are scenario inputs: start with the Matterhorn/Zermatt Alps and
  the Yosemite Sierra. For each: fetch the Copernicus GLO-30 tiles covering
  it from the public AWS bucket (no auth), ingest through the EXISTING
  Phase 4 DEM pipeline (core/terrain/dem.py), and hold it to the Gate 4
  verification discipline — ingested elevations checked against the source,
  CRS and tile IDs and sha256 recorded in the render manifest.
- Georeference for real: set the spec's latitude/longitude to the actual
  place, pin the scene's georeferencing origin there, and place the terrain
  at its true position and true heights relative to the flight — the
  ridgelines in frame are the real mountain's ridgelines. State the
  resolution limit honestly in VALIDITY.md (GLO-30 is 30 m posting).
- Wire the EXISTING orographic-lift provider (core/environment/terrain_field)
  to the same baked raster in windy scenarios, so wind over the real ridge
  produces the updrafts/sink the headless physics already models. Null-test
  it in the render path like Gate 3 does headless.
- Physics coupling, done honestly: default clips fly with spec-consistent
  terrain as declared. Stretch goal: give the real terrain collision in the
  UE host and matching heightfield ground queries headless, and show AGL
  parity over the real ridge. If too large, document as not done — never let
  visual mountains imply the gear model felt them.
- Materials: slope/altitude-driven (rock above treeline / scrub / valley
  floor / snow above the local snowline), labeled as approximated. Time of
  day (dawn / noon / low sun) as a parameter. §6.6 gotchas and manual
  exposure stay. Gate 6 must still pass.

## 3. Turbulence in the Unreal host
- Replicate the exact property writes core/environment/turbulence.py makes
  (turb-type, gains, W20, seed), configured once after trim, never per step
  (re-seeding destroys the correlated noise). Respect the seed-saturation
  guard (< INT_MAX).
- Test same-seed parity between hosts honestly: if the realization matches,
  add turbulence to the host-parity matrix under existing tolerances; if
  not, MEASURE why, keep the parity path refusing it, and mark it
  visual-only with the seed recorded.
- Null-test guard either way: the UE turbulent run's load-factor RMS must
  rise measurably over calm — proof turbulence reached the FDM, not a
  camera shake. Mutation-check it.

## 4. Condition matrix
- One command (experiments/showcase_matrix.py) renders the clip set:
  {calm, 25 kt crosswind, 15 kt gusty headwind, moderate turbulence w/seed}
  x {clear, hazy} x {dawn, noon} on 2+ airframes over the two REAL terrains
  plus one synthesized control terrain. Anything genuinely unimplementable
  is SKIPPED loudly, never faked.
- Each clip: 720p30, 20+ s, mp4 (ffmpeg at /opt/homebrew/bin), manifest row
  with spec digest, terrain tile IDs + sha, mesh + license, conditions, seed.
- Deliver a contact sheet plus the mp4s.

## 5. Honesty requirements (non-negotiable)
- Every visual claim measured or listed as not-established in VALIDITY.md;
  every new guard mutation-checked; physics stays the spec's and every
  scenery-only-terrain clip is labeled as such.
- If any step can't be done headlessly on this machine, stop and say exactly
  what is needed instead of substituting something quieter.

## Operational notes from the session that wrote this (read before starting)
- The whole Phase 5/6 toolchain works and is committed: see NEXT.md for the
  run commands, the six load-bearing commandlet behaviours, and the three
  patched upstream plugin bugs.
- Renders MUST pass `-stdout -FullStdOutLogOutput` and absolute paths, or the
  editor stalls / cannot find the card (measured; gate6_visual.py shows the
  working subprocess pattern).
- Builds use scripts/build_ue.sh (DEVELOPER_DIR pinned; no sudo, no
  xcode-select). Commandlets need no Xcode at all.
- Discard the AndroidFileServer block runtime appends to
  ue/Config/DefaultEngine.ini; never commit its token.
- Full verification loop: .venv/bin/pytest (227), scripts/mutation_check.sh
  (41 guards), then the gate scripts. Keep them green after every section.
