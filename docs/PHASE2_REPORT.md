# Phase 2 -- the annotated, randomised dataset pipeline: report

One report, a section per package, in the order the packages landed.
Each section says what was built, how to demonstrate it on any
platform, what was NOT verified in this environment, and the known
limitations -- the PHASE10_REPORT.md form. The shapes every package
shares are on docs/PHASE2_CONTRACTS.md; a section here names the
contract clauses it implements and states plainly where it landed
something the contract left open.

## P2-A/spec8 -- the SPEC_VERSION 8 bump and `scene.terrain_source`

**What was measured, and what was defective.** Three things were
measured before anything was built. (1) `examples/cameras_mountain_refusal.yaml`
did NOT refuse with the command its own header gave unless
`--synth-terrain` was added: the spec carried no terrain reference,
so `ScenarioSpec.read` + `validate()` reported it valid and the CLI
flew it over the flat datum (the buried camera is 2500 m above that).
The test that ran it passed the flag, so the suite never saw the
documented-command mismatch. (2) `Violation.render()` crashed with
`ValueError: Unknown format code 'g' for object of type 'str'`
whenever `validate_randomization` refused a year (`limit="1950-2050"`),
a day/hour/fog range, or the sun floor (`"-90..90"`): every CLI path
that prints a report would have printed a traceback instead of the
refusal's name. (3) The version-7 reader tolerates unknown top-level
keys, so a spec-8 block read by a version-7 build would have been
DROPPED in silence -- the reason the bump is not optional.

**What was built** (contracts §0, §2.1, §2.2, §5.2 shape, §10, §11, §12).

* `SPEC_VERSION` 7 -> 8, done as 6 -> 7 was: a version-7 dict refuses
  with the same named `ValueError` ("spec_version 7 is not supported by
  this build (expects 8)"); the eight spec examples were regenerated
  THROUGH THE WRITER (a scratch script loaded each, set the version,
  wrote `spec.to_yaml()` back under the byte-identical header comment)
  -- measured: seven differ from HEAD by the version line alone; the
  mountain example additionally gains its `scene` block and a header
  that drops `--synth-terrain`. The committed version-7 examples are
  frozen byte-identical under `tests/data/spec7_examples/` and a test
  upgrades each and asserts the version-8 canonical form is the frozen
  form plus the version line (absent blocks are canonical; the digest
  rule is re-implemented in the test, not imported).
* Four optional, absent-canonical blocks, every field a provenanced
  `Quantity` behind the spec's own `set()`/`plan()` front door, a
  stated field never silently moved:
  `scene` (`terrain_source` auto|flat|synthesised|baked, `terrain` bake
  stem) and `taxonomy` (`classes`, the documented six-class list) and
  `traffic[]` (`aircraft`, `track`, `range_m`, `livery`; at most two)
  in the new `core/scenario/blocks.py`; `randomization.policy` as one
  provenanced Quantity whose value is the §5.2 mapping (carried on the
  spec, serialised under the block; the block's own reader is
  untouched); `cameras[].exposure` (`aperture_f`, `shutter_s`, `iso`;
  f/8, 1/500 s, ISO 100 per preset) as a nested block on `CameraSpec`,
  addressed `cameras[i].exposure.<field>`, omitted when it is the
  preset's default so every spec-7 camera keeps its digest.
* Refusals by name: `scene.terrain_source`, `scene.terrain`,
  `taxonomy.classes` (empty, non-string or repeated), `traffic.count`,
  `traffic.aircraft` (not in `assets/aircraft_config/`),
  `traffic.track`, `traffic.range_m`, `randomization.policy` (a leaf not
  of a documented form: choice / uniform / loguniform / normal /
  lognormal / beta / weibull / poisson / uniform_dates with `weights`,
  `clip`, `gated_by`, `max`; fixed scalars at the top level only, so a
  misspelt distribution inside a group is refused rather than read as
  a group), `camera.exposure` (non-positive). All ride the core
  `validate()` surface. `Violation.render()` shows a non-numeric
  actual/limit verbatim.
* `scene.terrain_source` honoured. CLI: `synthesised` synthesises the
  ridge at the origin exactly as `--synth-terrain` does (the flag is
  now an alias and its help says so); `flat` forces the datum; `baked`
  uses `--terrain` or the spec's `scene.terrain` and refuses
  `scene.terrain` when neither names a whole bake; `auto` is the
  previous block unchanged; a flag that contradicts a stated source
  refuses `scene.terrain` (nothing is dropped in silence). Web app
  (`pick_scene`): `flat` and `synthesised` are honoured (`synthesised`
  writes the SAME raster under `TERRAIN_DIR` -- same name and cache key
  as the CLI, so the two share it); `baked` returns a scene carrying
  `refused: terrain.unbaked` that `needs_dynamic_bake` surfaces as the
  existing 409, whatever the coordinates' source; `auto` is
  `_auto_scene`, the previous body verbatim.
* The mountain example refuses AS DOCUMENTED with no flag (measured:
  exit 2, `[camera.terrain_clearance] ... -545.5 m AGL`); its test runs
  it without the flag, a second test keeps the flag working on an
  `auto` spec, and a parametrised test runs EVERY example through its
  header's stated outcome with no flags.
* Also: `tests/test_scenario_spec.py`'s version test renamed and
  re-documented for 8; `core/scenario/runner.py`'s "no RNG anywhere"
  sentence corrected; `docs/PHASE2_CONTRACTS.md` §11/§12 state the
  landed shapes and names.
* 15 mutation guards in `scripts/mutation_check.sh` (section "Phase 2,
  package A"), each confirmed by hand to fire.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_spec8_blocks.py
    .venv/bin/python -m flightsim.capture examples/cameras_mountain_refusal.yaml --out runs/buried
    # -> REFUSED [camera.terrain_clearance] ... m AGL, with no flag
    .venv/bin/pytest -q -p no:warnings tests/test_camera_cli.py -k "mountain or alias or contradicts or every_example"
    .venv/bin/pytest -q -p no:warnings tests/test_webapp.py -k terrain_source
    .venv/bin/python - <<'PY'
    from core.nl.compiler import compile_prompt
    from core.scenario.validate import validate
    s = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    s.set("randomization.enabled", True); s.set("randomization.year", 1800)
    print(validate(s, check_feasibility=False).render())   # used to raise
    PY
    ./scripts/mutation_check.sh          # the package-A guards report ok

**Not verified here.** Nothing in this package touches C++ and no
engine ran. The web app's `synthesised`/`baked` selections were
exercised through `pick_scene`/`needs_dynamic_bake` and the 64-px
synthesis in tests, not through a browser `/run` to a render; the CLI's
`baked` path was exercised with a stated missing stem and with no stem
(refusals), not with a real GLO-30 bake (none is on this machine). The
first Windows run with `scene.terrain_source: baked` + a curated bake is
the verification step for that path.

**Limitations (stated, not claimed).** No sampling of a policy, no
traffic composition, no exposure -> EV100 mapping: the fields, their
provenance and their SHAPE validation only (packages F, B and the Look
lane). `randomization.policy` lives on `ScenarioSpec.randomization_policy`
rather than inside `RandomizationSpec` (whose reader refuses unknown
keys and was not this package's file); the on-disk shape is the
contract's and F may move the attribute. A `synthesised` scene on the
web app is not caught by `apply_historical_weather`'s
`weather.not_a_place` rule (which keys on the control ridge's key) --
a stated date over a synthesised ridge at real coordinates would fetch
ERA5 for those coordinates; that function was not this package's to
edit. `render.json`/manifest carry no `terrain_source` yet (the
manifest scene block is schema-checked; adding a key is a manifest-6
item). Observed, not fixed: the existing guard "a failed model build
fails the run BY NAME" targets a line that occurs three times in
`webapp/runs.py` at HEAD (mutate() takes the first).

## P2-A/mesh-origin -- the mesh origin is MEASURED from the vertices, not assumed from the VRP

**What was measured, and what was defective.** eb5c71d (mesh manifest
version 2) set `mesh_origin_actor_cm` -- the point the render
commandlet attaches the body and every hinge at -- to the STAGED
JSBSim FDM's VRP, on the argument that FlightGear models are built about
their FDM's VRP. Measured from the pinned `.ac` files with the
repository's own reader (`assets_pipeline.acmodel.parse_ac` +
`world_vertices` + `ac_to_ue`), over the vertices the converter actually
writes, in the UE actor frame about the model's own origin:

| Airframe (pinned commit) | forward extreme (nose) | aft extreme (tail) | span | `labels.dimensions_m.length` | lowest gear vertex |
|---|---|---|---|---|---|
| B747 (`FGMEMBERS/747-400` @ 887ff474, 73 947 drawn verts) | **+29.80 m** | -41.14 m | 70.94 m | 70.66 m (0.4 %) | -5.62 m (nose wheels; gear .ac) |
| A320 (`FGMEMBERS/A320family` @ 3764d88a, 93 279) | **-2.53 m** (the origin is AHEAD of the nose) | -40.09 m | 37.57 m | 37.57 m (0.0 %) | none: the config lists no gear part |
| c172p (`c172p-team/c172p` @ a15d83d1, 132 798) | **+2.14 m** | -6.09 m | 8.23 m | 8.28 m (0.6 %) | -1.37 m (`NoseWheel`) |

Each mesh was modelled against its OWN repository's FDM (the 747-400's
own `747-400.xml` has VRP (1263, 0, 0) in; the staged `B747.xml` has
(1327, 0, -24)), and the A320 is not built about any VRP. With the
staged-VRP rule the drawn nose lands, along x, **-3.91 m** from its
label on the B747 (mesh AFT of its label), **-19.32 m** on the A320 (a
new 19 m error where the datum bug had left 2.5 m), **+0.10 m** on the
c172p (right by luck). These residuals are asserted by the
pinned-source test below (`vrp_rule_residual_cm`), so the finding is
measured on every machine with network, not stated once here.

**What was built** (contracts §0 mesh-manifest row, §0.1, §11
`aircraft.mesh_extent`).

* `assets_pipeline/convert.py`: mesh manifest **version 3**. While
  converting, `MeshExtents` accumulates the extents of every DRAWN
  vertex (after the config's exclusions and the glass drop) in the
  actor frame about the model origin, plus the lowest z over vertices
  of gear-matched parts/objects. The origin is then
  `x = nose_keypoint_actor_cm - mesh_nose_cm` (the labels' `nose`
  keypoint from `core/capture/airframe.load_airframe`, body frame about
  the CG, mapped to the actor by `actor = CG_actor + (fwd, right, -down)`,
  i.e. the plugin's (-x, y, z) about the zero datum); `y = 0`;
  `z = main_gear_contact_actor_cm - gear_lowest_cm` (the lower of the
  labels' `left_main_gear` / `right_main_gear` FDM contacts) where gear
  vertices are identifiable, else the VRP z **with the basis saying so**;
  the config's documented `model_origin_offset_m` on top, unchanged.
  Measured origins written: **B747 (-2979.8, 0, +13.9) cm**, **A320
  (+252.6, 0, -94.0) cm** (z from the VRP: no gear geometry), **c172p
  (-118.3, 0, +97.4) cm** (its measured z agrees with its VRP z to
  0.4 cm -- the one mesh that IS built about its VRP). eb5c71d wrote
  -3370.6, -1679.2 and -108.2.
* Refusal **`aircraft.mesh_extent`** (`ConvertError.constraint`; the
  converter CLI prints `REFUSED -- aircraft.mesh_extent: ...` and exits
  2, never a traceback) when |mesh span - labelled length| / labelled
  length > 5 %; the message names the likeliest cause -- a wrong unit
  (the ratio is 39.37, 3.28, 100 or their inverses), a wrong frame (the
  mesh's y or z span is the labelled length), else a wrong mesh -- and
  states that `model_origin_offset_m` cannot fix it.
* The manifest carries the measurement beside the number:
  `mesh_extents_actor_cm {nose, tail, lowest, gear_lowest|null}`,
  `mesh_extent_actor_m {x, y, z: [min, max]}`, `mesh_length_m`,
  `labels_length_m`, `mesh_origin_basis` ("measured from vertices: nose
  keypoint (x), main-gear contact (z)" | "... VRP (z: <reason>)" | "FDM
  VRP (<reason>)"), `origin_anchor {x, z}`, `origin_measurement` (the
  nose keypoint used with its basis and source, the main-gear contact
  used, the raw numbers, the length deviation), `mesh_origin_measured_actor_cm`
  (before the config offset), `vertices_measured`, `gear_vertices_measured`,
  `gear_geometry`; `vrp_actor_cm` and `vrp_source` stay for reference.
* New documented config key `gear_geometry {parts: [regex], objects:
  [regex], source}` in `B747.json` (the whole `747-400_gear.ac`),
  `c172p.json` (`.*Wheel.*`) and `A320.json` (empty, stating that the
  config lists no gear part and why z falls back). Malformed patterns
  refuse by name rather than moving the anchor in silence.
* A config with no `labels` block (DHC6) keeps eb5c71d's VRP rule,
  byte-identical, with a basis that does not start with "measured from
  vertices" so `drawn_airframe` can grade it by name; a labels block the
  labeller cannot resolve refuses `camera.labels` here rather than at
  capture time.
* `assets_pipeline/importer.py`: `MESH_MANIFEST_VERSION` 3;
  `stale_manifest_reason` names the version-2 reason ("assumed from the
  staged FDM's VRP, not measured") separately from the version-1 one,
  so `ensure_model` and `scripts/import_aircraft.py` re-convert every
  eb5c71d manifest on every machine (no editor time: same geometry).
* Tests (`tests/test_aircraft_assets.py`): a synthetic `.ac` whose
  extents are known by construction (nose +5 m, tail -5 m, wheel at
  -1.2 m) under a synthetic FDM (NOSE_TIP 10 in ahead of the datum,
  main gear 60 in below it) pins the rule (origin (-474.6, 0, -32.4)
  cm, not the VRP's (-203.2, 0, 12.7)), the three refusal wordings, the
  CLI's named exit 2, the z fallback and its basis, the no-labels
  fallback, the offset, the malformed-config refusals, and the stale
  rules for versions 1, 2 and a field-less 3. The pinned-source test
  fetches the three model repositories at their pinned commits with the
  importer's own `fetch_source` (reusing `assets/aircraft_src/` when it
  is already at the pin, or `FLIGHTSIM_AIRCRAFT_SRC_CACHE`), converts
  each, and asserts the table above to +-5 cm, the origins to +-1 cm,
  that origin + mesh nose equals the labelled nose re-derived from the
  FDM XML WITHOUT the converter (to 0.1 mm), and eb5c71d's residuals.
  When the network refuses it SKIPS BY NAME ("network refused: fetching
  <repo> @ <commit> ... the pinned-mesh measurements were NOT made
  here"; measured by rewriting github.com to a dead port: 3 skipped
  with that reason).
* Four mutation guards, each confirmed to fire by hand (apply, run
  `tests/test_aircraft_assets.py -k "not pinned"`, restore
  byte-identical by sha256, purge caches): the extent refusal (1 test
  fails), the x rule replaced by the VRP (3 fail), the z rule replaced
  by the VRP (2 fail), `importer.MESH_MANIFEST_VERSION` back to 2 (2
  fail). NOTE: the four `mutate` entries were swept into commit 28e78fa
  (the spec-8 package's `git add scripts/mutation_check.sh` in this
  shared checkout) before this package's own commit; they are the
  block headed "Mesh origin: measured from the vertices" there.
* `NEXT.md` gotcha 31 amended in place: what eb5c71d got wrong, the
  measured rule, the three origins, the Windows verification step.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_aircraft_assets.py -rs
    # the three pinned-source tests fetch ~1 GB once (or reuse assets/aircraft_src);
    # set FLIGHTSIM_AIRCRAFT_SRC_CACHE=<dir> to keep the fetch between runs
    .venv/bin/python scripts/import_aircraft.py B747 A320 c172p --no-import
    # -> "re-converting: manifest version 2 predates 3: its mesh origin was
    #     assumed from the staged FDM's VRP, not measured ..." on an eb5c71d tree
    .venv/bin/python assets_pipeline/convert.py assets/aircraft_config/B747.json
    # -> mesh extent  nose +29.80 m, tail -41.14 m ... lowest gear -5.62 m
    #    mesh origin  (-2979.8, 0.0, 13.9) cm ... measured from vertices: nose keypoint (x), main-gear contact (z)
    # the refusal, on the real mesh: copy B747.json, set labels.dimensions_m.length to 37.57, convert it:
    # -> REFUSED -- aircraft.mesh_extent: the converted B747 mesh spans 70.94 m ... says 37.57 m -- 88.8% off ... Likeliest: a wrong mesh ...   (exit 2)
    ./scripts/mutation_check.sh          # the four "Mesh origin" guards report ok

Measured on this Linux clone: `tests/test_aircraft_assets.py` +
`test_phase6b.py` + `test_camera_cli.py` + `test_camera_airframe.py`
96 passed (the three pinned-source tests measured, not skipped);
`test_webapp.py` + `test_camera_verify_corruption.py` +
`test_camera_labels.py` + the assets suite 127 passed.

**Not verified here.** No engine: nothing here has been rendered. The
commandlet already attaches at `mesh_origin_actor_cm` from the manifest
(eb5c71d, UNCOMPILED here; the first Windows build verifies) and reads
the same key name, so no C++ changed in this package. The Windows
step is NEXT.md gotcha 31's: re-convert (any of the three paths above
re-converts a version-2 manifest), render one frame with `-mesh=`, look
at the overlay -- the manifest CG must sit ON the airframe -- and run
`flightsim.verify`. The mesh-vs-label residual on a rendered frame is a
pixel measurement (`mask_vs_geometry`, package D) and is not claimed.

**Limitations (stated, not claimed).**

* The mesh nose is aligned to the LABELLED nose, whose own basis may be
  an estimate: the B747's nose keypoint is the structural datum taken
  as the nose tip (`basis: estimate`). If the type's nose sits 1-3 m
  from the datum, the label, not the mesh, is what is off, and the
  rendered residual will say so; the rule follows the label as stated.
* z compares the LOWEST gear vertex with the MAIN-gear contact. The
  nose-gear height is not compared: the 747 mesh's nose wheels sit
  0.83 m below its main wheels, its FDM puts the nose contact 0.25 m
  above the mains -- a 1.1 m mesh/FDM disagreement recorded in the
  config, not resolved.
* The A320 config lists no gear part (the repository has
  `Models/LandingGears/`), so the drawn A320 has no wheels and its z is
  the VRP's, stated. Adding those parts with their assembly-XML offsets
  is the item that would make its z measured; it changes what is drawn
  and was not done in a "new keys only" config change.
* y is not measured against anything (the y extents are recorded:
  B747 +-32.71 m, A320 -16.99/+17.02 m, c172p +-5.66 m). Rotational
  offsets in the model XML (the c172p's -3 deg pitch) are not applied.
* Contract deviations, stated: `mesh_origin_basis` is the exact string
  "measured from vertices: nose keypoint (x), main-gear contact (z)"
  (or the VRP-z variant) rather than the bare "measured from vertices"
  of contracts §0.1 -- a grader should match the prefix; the contracts
  page was not this package's file. `aircraft.mesh_extent` exits 2 from
  `assets_pipeline/convert.py`; `scripts/import_aircraft.py` (not this
  package's file) still reports every converter refusal as FAILED via
  `aircraft.mesh_import`, exit 1, printing the converter's REFUSED
  line. Both the task's `mesh_extents_actor_cm` shape and the
  contract's `mesh_extent_actor_m` shape are written.
* Verifier follow-ups (`core/capture/verify.py`, not this package's
  file): `DRAWN_MESH_MIN_MANIFEST_VERSION` is still 2 and
  `drawn_airframe` does not yet grade `drawn.origin_basis`, so a render
  from an eb5c71d manifest would still PASS that check until the
  verifier owner lands contracts §0.1's consequence.
