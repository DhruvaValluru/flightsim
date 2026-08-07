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
| 6B real assets + conditions | — | **built and measured; see below** |
| 7 experiments/V&V | 7 | PASS 6/6 |

```bash
.venv/bin/pytest                  # 249 tests
./scripts/mutation_check.sh       # 48 guards, all load-bearing
./scripts/ue_preflight.sh         # should say "Preflight OK"
./scripts/build_ue.sh             # builds the UE host
```

Phase 6B experiments, each self-contained and re-runnable:

```bash
.venv/bin/python experiments/gate5_realmesh.py    # on-screen clauses vs real meshes
.venv/bin/python experiments/turbulence_ue.py     # null test + same-seed parity verdict
.venv/bin/python experiments/orographic_ue.py     # port cross-check + coupling null test
.venv/bin/python experiments/showcase_matrix.py   # the 96-cell condition matrix
```

## Phase 6B: what was built (2026-08-06/07)

Full claims and non-claims: docs/VALIDITY.md §1.6b. Summary:

* **Real meshes.** FlightGear 747-400 and c172p (both GPL-2.0, commits in
  `assets/aircraft_config/*.json`) converted to per-part OBJs with hinge
  manifests (`assets_pipeline/`), imported headlessly, assembled by the render
  commandlet under `-mesh=`. §1.4 pairing enforced at conversion AND at
  render. Gate 5 on-screen clauses re-measured against both: r=0.99918 (747),
  r=0.99931 (c172p). Gate 5 proper (boxes) unchanged and green.
* **Real terrain.** GLO-30 → `core/terrain/glo30.py` (fetch, mosaic, ingest
  via the Phase 4 pipeline, verify vs source + named-summit identity; a bake
  that fails verification refuses to exist). Matterhorn/Zermatt and Yosemite
  baked in `runs/terrain/`. Rendered georeferenced (`-GeorefTerrain`): every
  vertex through the same PROJ chain that places the aircraft. GLO-30 is a
  30 m DSM — the source itself puts the Matterhorn at 4329 m vs 4478
  surveyed; that is the data, recorded, not a pipeline bug.
* **Turbulence in the host.** Cards carry the Dryden provider's exact writes;
  applied once after trim (`ConfigureTurbulence`). Null test: n_z RMS x323
  over calm. Same-seed parity measured and REFUSED (diverges from the first
  flown sample; each host bit-repeatable alone) → turbulent clips are
  visual-only with seed recorded; the parity path still refuses turbulence
  without `-AllowNonParityEnvironment`.
* **Orographic coupling.** C++ port in the render path
  (`FlightSimOrographic.cpp`), parameters all computed in Python and carried
  in the card. Cross-checked per render against the original provider
  (selftest grid in the manifest): max diff 1.78e-15 m/s. Null test: 2.58 fps
  RMS vertical wind coupled, 0.0 severed. AGL/collision stretch goal NOT
  done — the gear still feels the flat slab, every manifest says so.
* **Condition matrix.** `showcase_matrix.py`: {calm, crosswind25, gusty15,
  turb_moderate} x {clear, hazy} x {dawn, noon} x {B747, c172p} x
  {matterhorn, yosemite, control}, plus complex combined cells (turb_severe,
  crosswind25_turb, storm25) on the clear/dawn + hazy/noon sub-grid = 132
  clips, 720p30 22 s, mp4 + contact sheet + manifest rows (spec digest, tile
  IDs + sha, mesh + license, conditions, seed). Gusts are precomputed
  per-step wind schedules from the headless providers — one gust model, not
  two. Every clip carries the `showcase_panel.py` telemetry strip: commanded
  vs achieved, from recorded evidence only.

## Toolchain facts that cost hours (do not rediscover)

Everything in the previous session's list still holds (renders need
`-stdout -FullStdOutLogOutput` + absolute paths; builds via
`scripts/build_ue.sh`, no sudo/xcode-select; discard the AndroidFileServer
block runtime appends to `ue/Config/DefaultEngine.ini`). New this session:

1. **Commandlets never tick the asset compiling manager.** A static mesh
   above the async-build threshold stays "compiling" forever and renders
   NOTHING while every capture reports success — small meshes build inline
   and show, which disguises it as a per-asset mystery. The render commandlet
   now calls `FAssetCompilingManager::Get().FinishAllCompilation()` before
   the first capture, next to the shader flush.
2. **Interchange builds Nanite by default** and the capture then draws the
   coarse fallback (3563 of 24471 triangles on the 747 body). Disabling
   Nanite AFTER import corrupts the asset instead. It must be off in the
   import pipeline options: `InterchangePipelineStackOverride` +
   `mesh_pipeline.build_nanite = False` (scripts/ue_import_aircraft.py).
3. **Degenerate UVs corrupt the whole mesh build** ("degenerate tangent
   bases ... may result in mesh corruption" is not hyperbole). FlightGear
   .ac untextured surfaces carry u=v=0 everywhere; the converter substitutes
   position-derived UVs for any zero-area UV triangle.
4. **`FPlatformMisc::GetSHA256Signature` asserts on Mac** ("No SHA256
   Platform implementation"). FlightSimHeightfield.cpp carries a
   self-contained FIPS 180-4 implementation for the sidecar integrity check.
5. **`FParse::Value` stops at commas** — `-chase=-170,0,16` arrives as
   "-170". Colon-separated: `-chase=-170:0:16`.
6. **FlightGear light billboards** (BeaconOff, StrobeLight.*, nav lights)
   import as oversized glow quads; they are excluded in the aircraft configs.
7. **.ac coordinate frame measured, not assumed**: model.x = ac.x (aft),
   model.y = -ac.z, model.z = ac.y; UE frame negates X, so triangle winding
   is reversed exactly once (assets_pipeline/acmodel.py docstring).
8. **Exposure bias is a scene parameter**: Gate 6's 11.0 suits its low sun;
   noon over snowfields overexposes at 11 and uses 9.5; dawn 10.5. Manual
   exposure per §6.6 always; the bias is constant per clip and recorded.
9. **The editor exit code is unreliable after a successful commandlet run**
   (trace-server shutdown noise). Trust `render.json` existing + the
   commandlet's own "wrote N frames", which the harnesses do.

## Render commandlet flags added in 6B

`-mesh=<mesh_manifest.json>` (real airframe; refuses a mismatched FDM),
`-GeorefTerrain` (true-position terrain + classified vertex-colour material +
matte backstop plane), `-sun-elev= -sun-azim=` (time of day),
`-fog-density=`, `-exposure-bias=`, `-chase=x:y:z`, `-NoOrographic` (null-
test control). Telemetry commandlet: `-AllowNonParityEnvironment` arms
turbulence/schedule/orographic cards for measurement runs; without it the
parity path refuses them, with the reason.

## Asset pipeline (build-time, all command-line)

```bash
git -C assets/aircraft_src clone https://github.com/FGMEMBERS/747-400   # pinned commits in configs
git -C assets/aircraft_src clone https://github.com/c172p-team/c172p
python3 assets_pipeline/convert.py assets/aircraft_config/B747.json
python3 assets_pipeline/convert.py assets/aircraft_config/c172p.json
# then, inside UE (imports OBJs, disables Nanite, verifies section counts):
UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript \
    -script="scripts/ue_import_aircraft.py assets/generated/B747/mesh_manifest.json assets/generated/c172p/mesh_manifest.json" ...
UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript \
    -script="scripts/ue_create_materials.py" ...
```

## Do not regress these (all previous entries still apply)

* On-screen clauses are decided by reading the PNGs; surface deflection is
  read off the scene components; parity compares on the recorded clock; the
  parity spec is open-loop; heading is compared on the circle.
* The parity path refuses turbulence because the refusal is now a MEASURED
  verdict (runs/turbulence_ue/report.json), not a placeholder. Do not
  "enable" it without re-measuring same-seed realisations.
* Turbulence configuration is written once after trim, never in the step
  loop; the seed guard (< INT_MAX) is enforced in Python AND at the card
  door in C++.
* The orographic C++ port carries no derived parameters — everything comes
  from the card, computed in `core/terrain/glo30.orographic_card_block`. If
  you change a constant in terrain_field.py, the selftest comparison fails
  until FlightSimOrographic.h changes too. That is the point.
* Real-terrain bakes must pass `verify_against_source` + `check_summits`;
  both are mutation-guarded. Every clip manifest must keep `physics_ground`
  and the turbulence `visual-only` label.
