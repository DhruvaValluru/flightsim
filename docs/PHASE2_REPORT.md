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

## P2-I/messages -- the message catalogue (package I, part 1: no UI yet)

**What was measured, and what was defective.** The refusal names were
enumerated from the code, not from the contracts page: a scanner
written in the test (regexes over `core/`, `webapp/`, `flightsim/` and
`assets_pipeline/`) finds 85 names in eight shapes -- `Violation("…")`
first arguments including the multi-line calls, `constraint=` keywords
and class attributes, `"constraint":` and `"refused":` dict literals,
`<X>Error("<name>", …)` positional constraints, `getattr(…, "constraint",
"<default>")` defaults, `"<name>: …"` message prefixes, and every
`REFUSED -- <name>:` line the CLIs print. Three findings from the scan.
(1) Contracts §11 listed `camera.track` and `camera.multi_render` as
error constraints; in the code `camera.track` exists only as a
`getattr` default in `webapp/capture.py` and `camera.multi_render` only
as the prefix of a `ValueError` message in `webapp/runs.py` -- both are
covered, but a scanner that read only `Violation(` and `constraint=`
would have missed both. (2) Three bare names have no section:
`trim`, `validation` and `weather` (the CLI's `REFUSED -- trim:` line
and the web app's `"refused": "validation"` / `"weather"` on a 409);
they are catalogued as spelled rather than renamed, because
`scripts/verify_phase1.sh` and the tests grep for the spellings.
(3) The dynamic names `randomization.{name}` in `validate_randomization`
expand to eleven real names (every `FIELD_ORDER` field the file names by
quoted literal); the contracts' "`randomization.<field>` (each
range/jitter field by name)" is now a list. Six `REFUSED --` lines carry
NO name (`flightsim/verify.py` L69, L116; `flightsim/capture.py` L162,
L391, L494, L621: a bare `{exc}` or "the render wrapper exited N") and
are left as a finding for their owners, not given invented names here.
The `Violation.render()` string-limit crash the critique named was
already fixed on HEAD (`_shown`), so the catalogue's string limits
(`1950-2050`) render verbatim without a special case.

**What was built.** `core/messages/catalog.yaml`: 158 entries -- the
85 names the code emits, the 23 verifier checks as `check.<name>` plus
the 7 checks §4 adds, the §11 names later packages will emit, `spec.version`
/ `manifest.version` / `compile.rejected` / `compile.unavailable` for the
exceptions that carry no constraint string, `verdict.{pass,fail,not_run}`,
and the progress states (`progress.campaign.*` from §6.1's `campaign.json`,
`progress.case.*` from the ledger, `progress.page.*` for the six page
states). Each entry is `{sentence, hint?}`: plain English, no field
names or identifiers (a test greps for `snake_case` and `dotted.names`
in every sentence), numbers through `{placeholders}`, a plural form
`{n:one|many}` picked by the value of `n`. `core/messages/__init__.py`:
`render(name, **params)`, `explain(obj) -> {"sentence", "hint", "rule"}`
over a `Violation`, the web app's five-key dict, an exception with a
`.constraint` (or one of the four classes the CLI names by hand), or a
`ValueError` whose sentence identifies it (`spec.version`,
`manifest.version`, the two `compile.*`). The parameters are the
refusal's own fields plus `shortfall` (limit − actual), `excess`
(actual − limit) and `count` (violations in a report), so
`camera.terrain_clearance` at actual −89.5 / limit 2 reads "The camera's
path drops 91.5 m below the minimum height above the ground; it must
stay at least 2 m above the terrain." A missing placeholder renders as
nothing and the sentence is tidied around the gap; nothing ever raises.
An unknown name returns the raw name with the technical message under
it -- and never an invented sentence. `python -m core.messages` lists
the catalogue; with a name and `key=value` pairs it renders one entry
and exits 1 when the name is unknown. `tests/test_messages.py` (18
tests): the scanner is pinned to one real site per shape and a floor of
80 names, so a regex that quietly finds nothing fails; coverage (every
scanned name and every `Check("…")` has an entry); liveness (every
entry is scanned, a check, a pinned exception sentence, or listed in
`ALLOWED_FUTURE` with its package -- and a name that lands must leave
that set); rendering with numbers, string limits, plurals for 1 and 3,
absent placeholders, the unknown-name fallback, the three 409 shapes,
and the command line. Three mutation guards in
`scripts/mutation_check.sh`, each applied by hand and confirmed to make
the test file fail, the source restored byte-identical: an entry
dropped from the catalogue at load time; the unknown-name fallback
replaced by an invented sentence; placeholder values dropped from the
sentence.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_messages.py
    .venv/bin/python -m core.messages | head -30
    .venv/bin/python -m core.messages camera.terrain_clearance actual=-89.5 limit=2
    .venv/bin/python -m core.messages camera.hazard_intersection actual=1
    .venv/bin/python -m core.messages camera.hazard_intersection actual=3
    .venv/bin/python -m core.messages no.such_name; echo "exit $?"
    .venv/bin/python -c "
    from core.scenario.validate import Violation
    from core.messages import explain
    print(explain(Violation('airspeed.stall_margin', 'below 1.05 x Vs',
                            actual=95.0, limit=118.2, unit='kt CAS')))"
    scripts/mutation_check.sh 2>&1 | grep -E "catalogue|invented|refusal's own numbers"

The last line prints three `ok` rows; a `WEAK` row is a finding.

**Not verified here.** Nothing in this package touches the engine or
the C++. The seven sentences for the §4 checks that do not exist yet
(`check.mask_integers_only` … `check.applied_intrinsics`) and every
`annotation.*`, `authority.*`, `storage.*`, `campaign.*`, `progress.*`
and `verdict.*` sentence describe the contract's stated meaning, not
measured behaviour; they sit in `ALLOWED_FUTURE` until their package
lands and removes them. `export.unverified_labels` was found in the
working tree's `core/dataset/export.py` (package E, in flight during
this build) and is therefore NOT in `ALLOWED_FUTURE`; if E's commit
does not carry that raise site, the liveness test names it. No web
page or endpoint reads the catalogue yet (part 2); the CLIs still print
the technical text.

**Limitations.** The sentences are one author's reading of each rule's
docstring and message; a rule with several distinct clauses under one
name (`camera.intrinsics` has six, `camera.identifier` seven) gets one
sentence that covers the family, with the producer's technical message
still the specific account. The plural form handles English one/many
only. The scanner reads source text, not the AST: a name built by
concatenation, or a `Violation` whose first argument is a variable,
would not be seen -- today none is, and the eight shapes are pinned by
test so a ninth shape is a test change, not a silent gap. `explain()`
classifies un-named exceptions by class NAME (`TrimError`,
`ClosureError`, `TerrainImpactError`, `WeatherUnavailableError`) and by
sentence fragment for the two `ValueError`s and `LLMCompileError`, so
it imports no producer; a renamed class or reworded sentence is caught
by `test_named_exception_sentences_still_exist` for the fragments and
NOT for the class names (a finding for part 2: name those four
exceptions in their own modules). This package appends to
`scripts/mutation_check.sh` and `docs/PHASE2_CONTRACTS.md`, which the
brief did not list under its files; the instructor's rules require
both and the additions are append-only.

## P2-E/export -- YOLO and Pascal VOC, the object reader, the format list and the card

**What was measured, and what was defective.** Four things, before
anything was built. (1) `kitti_label_line` read a per-frame
`engine_labels` key that no producer in the repository writes, so
KITTI `occluded` was 3 (unknown) on every run by construction -- a
dead branch, admitted in the Phase 10 report. (2) A with-pixels
WebDataset shard was NOT reproducible: `tar.add(path)` recorded the
source PNG's mtime/uid/uname, so the same run exported twice gave
different bytes (the Phase 10 test only covered the labels-only path;
the new byte-identity test shows the frozen writer's first member
carrying a PAX `mtime` header of the fabrication clock). (3) COCO
categories were one per AIRFRAME name, so a taxonomy (contracts §2.1)
had nowhere to land, and there was no `segmentation` even where an ID
mask exists. (4) The card took `label_conventions` from `runs[0]`
only and named no licence for any asset drawn.

**What was built** (contracts §1, §3 for the records consumed; §6.2
export layouts; §11 refusals; plan package E).

* Two new writers over the same `Sample`, `core/dataset/export.py`:
  `yolo` (the Ultralytics detect layout -- `images/<split>/`,
  `labels/<split>/<key>.txt` with `class cx cy w h` normalised from
  the CLIPPED `bbox_2d`, 0-based class index in taxonomy order,
  `data.yaml` with `path`/`train`/`val`/`test`/`names`; every split's
  two directories exist even when empty) and `voc` (the devkit layout
  at ONE root -- `JPEGImages/<key>.png` as the PNGs are,
  `Annotations/<key>.xml` with folder/filename/size and one `object`
  per labelled object carrying `name`, `truncated`, `occluded`,
  `difficult`, `bndbox`; `ImageSets/Main/{train,val,test}.txt`).
  `bndbox` is the devkit's 1-based inclusive integer box covering the
  float box (`floor+1 .. ceil`). The flags derive from the label
  record: `truncated` = `fraction_in_frame < 1` when a record carries
  that key, else `truncation > 0`; `occluded` = `visible_fraction <
  0.9` (0 when no visibility was recorded -- stated in the card);
  `difficult` = the clipped box's longer side under the not-claimed
  pixel threshold (the object's own `objects_under_px: N` entry, else
  `NOT_CLAIMED_EXTENT_PX = 16`, a `#:`-documented module constant).
  The contracts' draft VOC layout (`<split>/JPEGImages`) is replaced by
  the devkit's single root, stated on the contracts page: the split
  lives in the ImageSets lists, which is what the devkit and
  torchvision read.
* The label source, `object_labels`: one entry per labelled object,
  primary first. When a frame carries `labels.objects[]` (manifest 6,
  contracts §3) every object is exported with its class resolved from
  its own `class`/`class_id` or through the manifest's `objects[]` by
  `id`/`int_id`; the primary takes the 2-D labels already mapped onto
  the exported image (so `--image sensor` keeps working for it), and
  any OTHER object under `--image sensor` needs its own
  `labels_sensor.objects[]` entry or refuses `export.sensor_labels`
  -- an ideal-pinhole box on a sensor image would be a silently wrong
  label. Without `objects[]` the one object is the primary airframe
  from the existing `labels` keys, class = the airframe name. The
  reader keys on the PRESENCE of `objects[]`, not the manifest
  version, so it reads on this build (manifest 5) and on the one that
  writes 6; both shapes are tested with fabricated manifests. The
  object list is carried OFF `Sample.labels`, so the WebDataset
  sidecar of a Phase 10 run is unchanged.
* The class list: `dataset_taxonomy` -- the manifests' `taxonomy` or
  `objects[]` (class_id order) when present, else the sorted airframe
  names exactly as Phase 10 wrote COCO categories; a run naming a
  taxonomy beside one that does not, or two different lists, refuses
  `export.taxonomy` (new name, added to §11): one dataset, one class
  list, never a guess.
* COCO, KITTI and WebDataset kept and extended: COCO categories from
  the taxonomy, one annotation per object, `visible_fraction` /
  `occluded_by` / `not_claimed` carried when recorded, and
  `segmentation` as uncompressed column-major RLE computed with numpy
  from the frame's `_mask.png` for the object's `int_id` (only where
  the mask exists; `area` stays `w*h`, `mask_pixels` carries the mask
  count). KITTI `occluded` from `visible_fraction` (>= 0.95 -> 0, >=
  0.5 -> 1, else 2; 3 when none was recorded), one line per object
  with both boxes, the dead `engine_labels` read removed. WebDataset
  members all written from bytes with mtime 0 / uid 0 / no names, plus
  `<key>.mask.png`, `<key>.class.png`, `<key>.depth.f32` when those
  files exist beside the frame.
* `export.unverified_labels` (contracts §4/§11): a run with a
  `_mask.png` on disk whose verification carries no PASS for
  `mask_integers_only` and `mask_vs_geometry` refuses the two formats
  that would ship the mask (`coco`, `webdataset`) by name; formats
  that ship no mask export; a run with no mask on disk (every Phase 10
  run) is unaffected. The two check names are package D's; until D
  lands, a rendered run with masks refuses these two formats, which
  is the intended direction of failure.
* `--format` takes a comma list (`parse_formats`: ordered,
  de-duplicated, unknown name refuses `export.format`). One format
  writes into `--out` as before; several write `--out/<format>/`
  each, with ONE card.
* The card (`dataset.json` + `DATASET_CARD.md`) gains: `formats` and
  `layout`; `images` and `instances`; `classes` with `class_order`
  (manifest taxonomy | airframe names) and `class_balance` (instances
  and images per class, overall and per split); `conditions` (stated:
  every `conditions` value with its count and source; sampled: per
  randomisation key n/min/max/mean for numbers, a count per value
  otherwise; `randomised_runs`); per run `seed`,
  `verification.status`/`file`, `masks_shipped`; the `split.policy`
  sentence beside the seed and assignment; `not_claimed_from_labels`
  (every distinct per-object `not_claimed` sentence with its record
  count, also appended to `not_claimed`); `licences` (per object from
  `objects[].licence`, and per airframe config from its `license`
  block read from this repository -- null WITH the reason when the
  file is not here); `label_conventions_by_manifest_version`; YOLO
  and VOC conventions beside COCO's and KITTI's.
* Refusals stay by name: `export.unverified` and
  `export.verification_failed` keep their sentences (both were already
  named); `export.unverified_labels` and `export.taxonomy` are new.
  The CLI prints `REFUSED -- <name>: <sentence>` and exits 2 for
  every one.

**Tests and guards.** `tests/test_dataset_formats.py`, 12 tests, each
round trip through an INDEPENDENT reader written in the test file:
pycocotools 2.0.11 (`requirements-dev.txt`; it installed in this
container and the tests use `COCO`, `mask.frPyObjects` and
`mask.decode`; a machine without it skips those two tests BY NAME
rather than passing them), a minimal YOLO text reader against the
Ultralytics layout, `xml.etree` for VOC, a minimal KITTI line reader,
`tarfile` for WebDataset -- image counts, category names/ids and box
coordinates to the pixel (YOLO within 0.01 px of the manifest's
`bbox_2d`, VOC integers within one pixel, COCO exact, KITTI to its two
decimals), the expected values read from `capture_manifest.json` with
json, never from the writer's objects. The Phase 10 writers are pinned
BYTE-IDENTICAL against a frozen copy of the pre-package-E module
(`tests/data/export_phase10_frozen.py`, loaded by path) for COCO and
KITTI with pixels and labels-only WebDataset. A fabricated manifest-6
run (three objects: primary, a small truncated part-occluded traffic
aircraft, terrain with a tight box only) checks every writer's
per-object output and each VOC flag and KITTI occluded value; a mixed
export refuses `export.taxonomy`; a sensor export of an object without
sensor labels refuses `export.sensor_labels`; a fabricated `_mask.png`
refuses `export.unverified_labels` for coco/webdataset, exports for
yolo, and after the two checks PASS ships as RLE that pycocotools
decodes to the fabricated rectangle's 24000 pixels and as a
byte-identical tar member; the split test exports all five formats
over the four-run batch and reads every tree back to assert no
simulation digest appears in two splits in any format and each format
agrees with the card. `tests/test_dataset.py` (14) passes unchanged.
Nine new mutation guards in `scripts/mutation_check.sh` (the
unverified refusal's NAME; the split lookup made per-frame; VOC
truncated via `truncation` and via `fraction_in_frame`; VOC occluded;
VOC difficult; KITTI occluded; the `export.unverified_labels` refusal;
the WebDataset member clock) -- each applied by the script's own
`mutate()` in isolation, its test file run, `export.py` restored
byte-identical (sha256 checked) and `__pycache__` purged: 9 of 9
fire. The six Phase 10 guards that target `export.py` were re-run the
same way against the new module: 6 of 6 fire. Not guarded, and said
so: the `export.taxonomy` mixed-list refusal in `dataset_taxonomy` --
removing it still refuses under the same name from `class_index`, so
a guard there reports WEAK; the refusal is belt and braces.

**How to demonstrate (any platform).**

    .venv/bin/pip install -r requirements-dev.txt          # pycocotools, the independent COCO reader
    .venv/bin/python -m flightsim.batch examples/batch_matrix.yaml --out runs/batch/demo
    .venv/bin/python -m flightsim.export runs/batch/demo --out datasets/demo --format yolo,voc,coco,kitti,webdataset --labels-only
    cat datasets/demo/DATASET_CARD.md                      # formats, class balance, conditions, licences, not claimed
    head -3 datasets/demo/yolo/data.yaml; ls datasets/demo/voc/ImageSets/Main
    .venv/bin/pytest -q -p no:warnings tests/test_dataset_formats.py tests/test_dataset.py
    ./scripts/mutation_check.sh                            # the nine package-E guards are in the P10-6 block's wake
    # Windows, with the engine: render the matrix (capture: render: true), drop --labels-only;
    # with package D's mask checks PASS, coco carries segmentation and webdataset the mask members.

**Not verified here.** No rendered run exists in this container:
every with-pixels path ran on fabricated flat PNGs of the manifest's
declared size, the mask path on a fabricated 8-bit rectangle, and the
manifest-6 object records are fabricated to the contracts' §3 shape --
the first Windows render with package B/C's real `objects[]` is the
check that the reader's key resolution (`class`/`class_id` on the
record or through `objects[]`) matches what the producer writes. No
training stack loaded a tree: the YOLO layout is asserted against
Ultralytics' documented structure by a minimal reader, the VOC tree
by `xml.etree`, not by `ultralytics.data` or `torchvision`. The two
mask checks the `export.unverified_labels` refusal looks for do not
exist until package D lands. Nothing here compiles C++.

**Limitations.** Objects without a 2-D box are not written by any
format (a scene object with only a tight box takes it as its box);
objects without a 3-D box are not KITTI objects. VOC has no "unknown"
occlusion, so an object with no recorded visibility is written
`occluded 0` (the card and the not-claimed list say so; KITTI keeps
3). The COCO `segmentation` is per-object RLE of the ID mask, so on a
run whose mask is still the single-value aircraft silhouette it is
the primary's silhouette. Under `--image sensor` only the primary's
sensor mapping exists today; other objects refuse by name until the
sensor model maps them. Croissant / HF `dataset_infos` twins and
Parquet (brainstorm §4) are not written. The realised-distribution
histograms are n/min/max/mean per sampled key, not binned coverage
(§5.5 is package F's). Exported images are copied, not linked.
