# Resume here

## State

| Phase | Gate | Status |
|---|---|---|
| 0 core FDM | 0 | PASS 9/9 |
| 1 spec + NL | 1 | PASS 4/4 |
| 2 TECS + closure | 2 | PASS 4/4 |
| 3 environment | 3 | PASS 5/5 + convergence |
| 4 terrain | 4 | PASS 7/7 |
| 5 Unreal | 5 | PASS 3/3 clauses, each measured |
| 6 visual realism | 6 | PASS 4/4 measured clauses + side-by-side |
| 6B real assets/terrain/turbulence/matrix | — | **DELIVERED, all verdicts measured** |
| 7 imagery/coupling/atmosphere | — | next: docs/BRIEF_PHASE7.md |

```bash
.venv/bin/pytest                          # 261 tests
./scripts/mutation_check.sh               # 49 guards, all load-bearing
./scripts/ue_preflight.sh                 # "Preflight OK"
./scripts/build_ue.sh                     # builds the UE host
.venv/bin/python experiments/gate5_ue_parity.py    # gate 5 end to end (see below)
.venv/bin/python experiments/gate6_visual.py       # gate 6 (~4 min)
.venv/bin/python experiments/gate5_realmesh.py     # gate 5 on-screen, real meshes
.venv/bin/python experiments/turbulence_ue.py --skip-runs    # re-verdict from disk
.venv/bin/python experiments/orographic_ue.py --skip-renders # port check from disk
.venv/bin/python experiments/showcase_matrix.py    # the 144-cell matrix (resumable)
```

## Phase 6B: what exists now and what was measured

* **Real airframes.** FlightGear GPL-2.0 meshes (commits pinned in
  assets/aircraft_config/*.json): 747-400 (FGMEMBERS) on the B747 FDM
  (which names itself B747-400) and the c172p-team Cessna on c172p. §1.4 is
  enforced twice: the converter refuses a mesh whose fdm_config name is not
  allowed, and the render commandlet refuses a manifest whose fdm differs
  from the card's aircraft. Pipeline: assets_pipeline/convert.py (.ac → per-
  part OBJ + hinge manifest, frames measured not assumed: model.x=ac.x,
  model.y=-ac.z, model.z=ac.y; UE negates X, winding reversed once) →
  scripts/ue_import_aircraft.py (UE pythonscript commandlet) →
  UFlightSimSurfaceAnimator bindings from the manifest. Gate 5 on-screen
  clauses re-measured on the real meshes: B747 bank-tracking r=0.9997,
  c172p r=0.9909 (runs/gate5_realmesh/report.json). Boxes path untouched;
  Gate 5 proper unchanged.
* **Real Earth terrain.** Copernicus GLO-30 via core/terrain/glo30.py:
  fetch (public bucket, no auth) → mosaic/crop → the EXISTING Phase 4
  dem.ingest → verify vs source (400 pts, p95 |Δ| 28 m Alps / 17 m Sierra)
  → summit identity checks → provenance (tiles+sha, EGM2008 note, DSM
  smoothing: the Matterhorn's own source data tops at 4329 m vs 4478
  surveyed — dataset limit, recorded). Scenes: matterhorn, yosemite +
  synthesised control ridge. Rendered georeferenced: every vertex through
  the GeoReferencingSystem's projected CRS (ProjectedToEngine), true
  position and heights; slope/altitude vertex-colour classification
  (labeled approximated), calibrated palette (see gotchas).
* **Turbulence in the UE host.** Card carries the exact Dryden property
  writes (turbulence_properties) computed by core/environment/turbulence.py;
  ConfigureTurbulence writes them once after trim+latch. Null test: n_z RMS
  ×323 over calm. Same-seed parity MEASURED AND FAILED: each host
  bit-repeatable alone, realisations diverge from the first flown sample
  (per-process RNG stream offset) → verdict **visual-only, seed recorded**
  (runs/turbulence_ue/report.json); telemetry commandlet refuses turbulent
  cards without -AllowNonParityEnvironment.
* **Orographic wind in the render path.** FlightSimOrographic.cpp is a
  line-for-line port of terrain_field.py; every parameter (wavelength,
  decay, projected origin) computed once in Python and carried in the card.
  Cross-check: 49-point selftest grid in every manifest, max |Py−C++| =
  1.78e-15 m/s. Null test: coupled RMS 2.58 fps vertical wind in the FDM,
  severed control exactly 0 (runs/orographic_ue/report.json).
* **Microburst.** core/environment/downburst.py: Vicroy vertical shaping,
  vertical velocity DERIVED from continuity (numerically checked,
  mutation-guarded), JAWS/Fujita magnitudes. Matrix cell at 300 m AGL with
  automatic visual-terrain clearance check (refuses rather than tunnels);
  field evaluated on the NOMINAL track (labeled — position-coupling is a
  Phase 7 item).
* **Condition matrix.** experiments/showcase_matrix.py: 144 cells = {calm,
  crosswind25, gusty15, turb_moderate} × {clear, hazy} × {dawn, noon} ×
  {B747, c172p} × {matterhorn, yosemite, control} + complex cells
  (turb_severe, crosswind25_turb, storm25, microburst) on the clear/dawn +
  hazy/noon sub-grid. 720p30 × 22 s; every clip composited with the
  telemetry panel (experiments/showcase_panel.py — commanded vs achieved
  from recorded evidence only). Resumable (skip-existing). Deliverables:
  runs/showcase/clips/*.mp4, contact_sheet.png, showcase_manifest.json.
* **Docs.** VALIDITY.md updated throughout; BRIEF_PHASE6B.md is history,
  BRIEF_PHASE7.md is next.

## Operational gotchas (each cost real time; do not rediscover)

1. **Renders**: absolute paths and `-stdout -FullStdOutLogOutput` or the
   editor stalls; `-RenderOffScreen -AllowCommandletRendering` or blank
   frames. gate6_visual.py render() is the canonical subprocess pattern.
2. **Builds**: scripts/build_ue.sh only (DEVELOPER_DIR pinned; never sudo /
   xcode-select). Commandlets need no Xcode.
3. **Unity builds merge anonymous namespaces** — but only for files CLEAN
   in git (adaptive unity excludes dirty files). Same-named constexprs in
   different .cpp files compile fine all session, then break the fresh
   clone / post-commit build. Names are per-file-unique now; keep them so.
4. **Async asset compilation**: commandlets never tick the compiling
   manager, so big StaticMeshes stay "compiling" and render NOTHING while
   captures report success. FAssetCompilingManager::Get().
   FinishAllCompilation() before the first capture (in the render
   commandlet, next to the shader flush). Measured: 747 body absent, its
   26-triangle ailerons present.
5. **Interchange import**: Nanite OFF at import time via
   InterchangePipelineStackOverride (a post-import flag flip corrupts the
   asset — measured). MikkTSpace OFF post-import via
   EditorStaticMeshLibrary (degenerate tangents corrupt the build —
   "may result in mesh corruption" means it). Converter substitutes
   position-derived UVs for degenerate UV triangles. And
   StaticMesh.get_num_triangles(0) reports the NANITE FALLBACK (3563 of
   24471) — count real geometry by summing per-section extraction.
6. **Vertex colours double-brighten**: the procedural mesh sRGB-encodes on
   store, the material reads bytes raw, and the atmosphere adds blue
   in-scatter at distance. The ClassifyVertex palette is CALIBRATED against
   rendered frames (correct-albedo maths rendered navy; naive linear
   rendered mint — both measured). Recalibrate by probe render, not theory.
7. **Fog and exposure are per-scene parameters**: clear=0.0012 at showcase
   altitudes (Gate 6 keeps 0.0025 at 300 m), exposure bias 9.5 noon / 10.5
   dawn / 11.0 gate6. All recorded in manifests.
8. **DefaultEngine.ini**: runtime appends an AndroidFileServer block with a
   token — `git checkout ue/Config/DefaultEngine.ini`, never commit it.
   The fixed-tick settings at the top are load-bearing.
9. **One editor at a time**: the matrix runs UnrealEditor-Cmd serially;
   don't launch probe renders while it runs (DDC/GPU contention). Kill via
   `pkill -f "UnrealEditor-Cmd.*FlightSimRender"` + `pkill -f
   showcase_matrix`; it resumes cleanly.
10. **mutation_check.sh mutates source in place** — never run pytest (or
    build cards) concurrently with it in a way that re-imports core/.
11. **Pillow is in the venv** (panel + contact sheet); ffmpeg at
    /opt/homebrew/bin/ffmpeg; fonts from /System/Library/Fonts/Menlo.ttc.
12. **You can look at frames**: Read any rendered PNG (or a python-cropped
    region) to verify visually. Several bugs this phase were caught only by
    looking. Probe pattern: runs/probe6b/card.json + short -seconds renders.

## Everything below is Phase 5 context that remains load-bearing

(unchanged: the six commandlet behaviours, the three patched upstream plugin
bugs re-applied by vendor_ue_plugin.sh and asserted by check_bridge_api.sh,
the parity discipline, and the do-not-regress list)

* The plugin's wind IC corrupts CAS → calm RunIC, wind via FGWinds props,
  re-trim (TrimInWind), same NED floats re-written every step.
* Trim snapshot exempt from comparison; heading compared on the circle;
  comparison on the recorded clock, never sample index.
* GetAGLevel cm/m ray bug (3.19 km reach) patched in VENDORED.json.
* Ground slab spawned for physics queries; aircraft placed by CG; actor yaw
  = heading − 90; LatchTrimmedControls after trim; render commandlet needs
  -AllowCommandletRendering; two warm-up captures discarded.
* On-screen clauses decided by reading PNGs; surface deflection read off
  scene component transforms; commandlets refuse what they cannot honour.
* docs/JSBSIM_CORRECTIONS.md before writing property code;
  docs/VALIDITY.md for what may be claimed.

## Next task: Phase 7 — docs/BRIEF_PHASE7.md

Owner authorized 2026-08-07, autonomous end to end. Step 0: finish the
matrix if incomplete (resumable, one command) and deliver clips + contact
sheet. Then Tier 1 (Sentinel-2 imagery drape, terrain collision + AGL
parity, lee-rotor turbulence measure-first), Tier 2 (boundary-layer shear,
thermals, position-coupled microburst, optional von Kármán), Tier 3 (the
evolving-conditions long flight — re-implement the reverted schedule
machinery COMPLETELY or not at all —, more airframes, paths/propellers/
cameras, same-seed RNG investigation). The brief carries the details and
the honesty bars for each.
