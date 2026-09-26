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
(As landed, `flightsim/capture.py`: an unreadable spec now prints
`REFUSED -- spec.read:` (a new name; its catalogue entry is an open
item on `catalog.yaml`), the host-flight error prints
`REFUSED -- capture.host_flight:` in the colon form rather than its
bracketed one, the render wrapper's exit prints `REFUSED --
camera.render:`, and the two `{exc}` lines are ScheduleError's, whose
text begins with `camera.schedule:`, which
`tests/test_capture_cli_words.py` asserts rather than assumes. The two
in `flightsim/verify.py` remain open.)
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

## P2-Look/1 -- the engine pin moves to 5.7 and the renderer is configured (nothing rendered)

**What was measured, and what was defective.** (1) The engine version
was stated in twenty places and pinned in none: `ue/FlightSim.uproject`
said 5.5, eleven scripts built a `UE_5.5` path or compared
`Build.version` against `"5.5"`, `core/util/platform.py` named 5.5 in
three refusal texts and two default install roots, and the README and
`docs/CAMERA_WINDOWS.md` told a person to install 5.5. No test read any
of them, so a move to another engine could leave a stale 5.5 in any one
of them and the suite would stay green. (2) `ue/Config/DefaultEngine.ini`
had no `[/Script/Engine.RendererSettings]` section at all (the ue-render
map): every Gate 6 number on record (`docs/VALIDITY.md` 2.13, macOS,
UE 5.5) was taken on engine defaults, with no record in any frame of
which defaults. (3) The vendored JSBSim plugin records the JSBSim tag and
commit it came from but not the engine it was vendored against, so the
preflight could not say "this plugin was measured on 5.5, you are on
5.7". (4) A first draft of the INI mutation guards read WEAK: `mutate()`
replaces the first occurrence and the ini's own comment block quotes
each `key=value` before the real assignment (NEXT.md gotcha 28, met
again in a text file); the targets are now two adjacent real lines.

**What was built.**

- The pin is 5.7 everywhere it is STATED (brainstorm 9.8, contracts
  section 10): `EngineAssociation`; the default install root and the
  `Build.version` comparison in `scripts/ue_preflight.ps1`; the install
  root in `build_ue.ps1`, `build_ue.sh`, `ue_preflight.sh`,
  `render_ue_scenario.sh`, `run_ue_scenario.sh`, `check_bridge_api.sh`;
  the next-steps text in `setup.ps1`, `setup.sh`, `deploy_windows.ps1`;
  the toolset message in `vendor_ue_plugin.ps1`; the README and
  CAMERA_WINDOWS install lines. `core/util/platform.py` gains ONE
  constant, `UE_ENGINE_VERSION = "5.7"`, from which the three
  `ue.platform` refusal texts and the mac/Windows default roots are
  built, so the Python side states the pin in one place. Where 5.5 was
  a MEASUREMENT (the v143 toolset, the Xcode 15.2-16.9 range, the
  vendored plugin's compatibility, the CAMERA_WINDOWS 0.00 m bound)
  the line keeps 5.5 and says "measured".
- `scripts/vendor_ue_plugin.{ps1,sh}` carry the engine they target
  (`$ueEngineTarget` / `UE_ENGINE_TARGET` = 5.7) and RECORD it in
  `VENDORED.json` as `ue_engine_target` on the next vendor run; the
  Windows preflight prints a note (not a Fail: the native library does
  not link the engine) when the key is absent -- as it is in the
  committed file, which predates the move -- or differs from 5.7, and
  points at NEXT.md gotcha 32. Gotcha 32 records that the three
  patched upstream C++ bugs (and the Build.cs staging patch) were
  measured on 5.5 against a plugin that states 5.0-5.6, so on 5.7 each
  patch may be unnecessary, still necessary or no longer apply, and
  that Gate 6, Gate 10-R and gotchas 4 and 5 are re-measured before
  any 5.7 frame is trusted.
- `ue/Config/DefaultEngine.ini` gains `[/Script/Engine.RendererSettings]`
  -- `r.CustomDepth=3` (stencil ids, contracts 2.3), Lumen GI and
  reflections in software (`r.DynamicGlobalIlluminationMethod=1`,
  `r.ReflectionMethod=1`, `r.Lumen.HardwareRayTracing=False`,
  `r.GenerateMeshDistanceFields=True`), virtual shadow maps
  (`r.Shadow.Virtual.Enable=1`), the Nanite project enable
  (`r.Nanite.ProjectEnabled=True`; the per-mesh import flag stays OFF,
  contracts section 10 and gotcha 5), TSR as the beauty default
  (`r.AntiAliasingMethod=4`; label passes override it to none per
  capture), the extended luminance range for the EV100 exposure
  (`r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange=True`),
  and `r.Substrate=False` with the reason in the file: no material on
  the branch is authored for it. A comment block above the settings
  names, per setting, the Gate 6 clause it is EXPECTED to move. It also
  gains `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` DX12 +
  SM6, which the three features need. Every pre-existing line, including
  the fixed-tick pair (gotcha 19) and the AndroidFileServer block
  (gotcha 8), is kept; the diff is 77 insertions and 0 deletions.
- Two tests in `tests/test_platform.py`:
  `test_the_engine_pin_is_5_7_everywhere_it_is_stated` sweeps the
  uproject, `platform.py`, every `scripts/*.ps1` and `*.sh`, README,
  CAMERA_WINDOWS and NEXT.md for the old pin in every spelling the
  tree used (`UE_5.5`, `UE 5.5`, `Engine 5.5`, `"5.5"`) and allows a
  hit only on a line that says "measured" or names 5.7 -- history is
  allowed by the word on the line, not by file, so a new stale pin
  cannot hide in an old document; it also reads the uproject back and
  checks the refusal texts and roots against the constant.
  `test_default_engine_ini_carries_the_look_lane_renderer_settings`
  parses the INI with a small UE-ini reader (case-preserving, array
  prefixes kept) and reads every setting back by section and key,
  Substrate OFF included, plus the fixed-tick lines. The two `UE_5.5`
  pins the older platform tests carried are now derived from the
  constant.
- Five `mutate` guards in `scripts/mutation_check.sh`, each confirmed
  BY HAND to fail `tests/test_platform.py` when applied and to restore
  byte-identical: the uproject back to 5.5; `UE_ENGINE_VERSION` back to
  5.5; a stale `UE_5.5` install path in `ue_preflight.ps1`; Lumen GI
  off in the ini; Substrate on in the ini.

**How to demonstrate (any platform).**

```
.venv/bin/pytest -q -p no:warnings -o addopts= tests/test_platform.py tests/test_powershell_scripts.py
grep -rn 'UE_5\.5\|Engine 5\.5\|"5\.5"' ue/FlightSim.uproject core/util/platform.py scripts/ README.md   # only "measured" lines remain
git diff HEAD~1 -- ue/Config/DefaultEngine.ini | grep -c '^-r\.'    # 0: nothing removed
.venv/bin/python -c "from core.util import platform as p; print(p.UE_ENGINE_VERSION); print(p.ue_platform_refusal())"
bash scripts/mutation_check.sh          # the five Look/1 guards report "ok"
```

On Windows, after `.\scripts\ue_preflight.ps1`: the engine line says
`UE 5.7.x`, and the `jsbsim plugin engine target` line says
"not recorded (vendored before the 5.7 pin; measured on 5.5)" until
`.\scripts\vendor_ue_plugin.ps1` has been re-run on 5.7.

**Not verified here.** No engine is installed in this environment, so:
the project has NOT been opened or built on 5.7 (the uproject and the
INI are text edits; UBT may report the `IncludeOrderVersion Unreal5_5`
in `ue/Source/*.Target.cs` as a warning); the vendored plugin has NOT
been re-vendored or compiled on 5.7 and its four local patches have not
been re-checked there; NONE of the renderer settings has been rendered
-- not one Gate 6 clause has been re-measured, no probe render against a
5.5 control exists, and the vertex palette (gotcha 6) and the three
exposure biases (gotcha 7) are known to be invalidated by Lumen and the
extended luminance range and have not been recalibrated; the commandlet
does NOT yet record `render.json.render_settings` (a later Look-lane
stage), so a frame rendered today carries no record of these switches;
the `.ps1` scripts are lint-checked, not executed (no PowerShell here);
the Xcode range the Mac preflight checks (15.2-16.9) was measured for
5.5 and 5.7's range is unchecked, as the script now says. What each
switch is expected to change is written next to it in the INI; what it
DOES change is the first measurement on the Windows box.

**Limitations.**

- Outside this stage's files and still naming 5.5: `ue/Source/FlightSim.Target.cs`
  and `FlightSimEditor.Target.cs` (`IncludeOrderVersion Unreal5_5` -- a
  compatibility marker; move it to `Unreal5_7` once the 5.7 build says
  so), `flightsim/capture.py` L118 (a message: "Windows with UE 5.5 and
  the bridge"), `experiments/fps_probe.py` L55-57 (Mac editor paths),
  and the historical measurement text in `docs/VALIDITY.md`,
  `docs/CAMERA_PHASE2_WINDOWS_PLAN.md`, `docs/vva/VV_REPORT.md`, which
  stays as taken. The sweep test does not cover them; capture.py and
  fps_probe.py are the two that should be moved in the next stage that
  owns them.
- The Windows install-root fallback sorts `UE_5.*` folders by name, so
  a future `UE_5.10` would sort below `UE_5.7`; the explicit default and
  `UE_ROOT` are unaffected.
- `r.Nanite.ProjectEnabled=True` is the project-level enable only. The
  measured finding (gotcha 5: the capture drew the coarse Nanite fallback)
  keeps the per-mesh import flag off, so on this branch the setting
  changes no drawn geometry until that finding is re-probed on 5.7; it
  is on so that the re-probe is a one-flag experiment.
- Substrate stays OFF by decision, not by measurement: nothing on the
  branch is authored for it. `r.Lumen.HardwareRayTracing=False` is the
  software-first default from contracts section 10; hardware RT is a
  Look-lane experiment on a card that supports it.
- The engine target the vendor scripts record is a statement of what
  they target, not a measurement of a 5.7 build; only the vendor run
  and the bridge build on Windows turn it into one.

## P2-F/randomization -- the policy, the prompt vocabulary and the look coupling

**What was measured, and what was defective.** (1) The compiler had
no randomisation vocabulary at all: `compile_prompt("varied weather
over the rockies with mixed traffic and random viewpoints at
different times of day")` returned an all-default B747 spec with
`notes == []` and no question -- a request for variety was silently a
request for nothing (re-confirmed on HEAD before this package). (2)
The sampler wrote every draw as `derived`, so a draw and a planner's
edit were indistinguishable in the record and a later planner could
move a drawn value. (3) The LLM parser's top-level key set was a
literal (`{'fields','notes','questions','cameras'}`), so a fifth key
would have refused every response until edited; the shape-sentence
assert did not cover it. (4) The Phase 10 example's sampled digest,
card block and `to_dict()` were recorded BEFORE any change
(`scratchpad/pkgF_baseline.json`) and compared after: byte-identical
(a test now pins the 20-key block and the same numbers beside a
policy). (5) The web page's `/compile` payload drops the `policy` key:
`webapp/server.py` L149 overwrites the page dict's `randomization`
with the block alone, so the digest the page shows differs from the
one `/run` re-reads once a policy exists (open item, not F's file).

**What was built** (contracts §5.1-5.5, as landed in §5.6; brainstorm
§5).

* `Source.SAMPLED` (`core/scenario/fields.py`, between `inferred` and
  `model`), with `detail = {policy, distribution, seed, draw_index}` on
  every drawn field; excluded from every plannable rule by
  construction and pinned by a test that tries all four doors (block,
  spec, camera, and a second sampler pass).
* `core/scenario/randomization.py`: `POLICY_LEAVES` /
  `POLICY_CAMERA_LEAVES` (14 leaves + the `cameras` group; each with
  its admitted forms, kind, bounds, target field), all nine
  distribution forms with `clip`, `gated_by` and `max`, `policy_stream`
  (SeedSequence per leaf and attempt from `[draw_index, campaign seed]`,
  `core.experiments.seeds` discipline), the attempt loop (a private
  copy of the spec per attempt, every leaf applied, the Phase 10 leaves
  run on top, `validate()` with the trim check as the gate; a refused
  draw is COUNTED with its values and re-drawn; 20 attempts then
  `randomization.infeasible` with every refusal in the error and the
  spec left untouched), `policy_draws` as the record, `render_look`
  extended with the look rows, `card_block` gaining one entry per
  sampled leaf plus `policy`, `policy_draws` and `look`, and
  `realised_distribution`. Existing keys keep their streams and bytes.
* `core/nl/compiler.py`: `RANDOMIZATION_WORDS` (phrase regexes ->
  families) and `RANDOMIZATION_FAMILIES` (the documented leaves per
  family, asserted at import against the sampler's table), range
  phrases ("across the Rockies") -> a `location` choice of that range,
  `apply_randomization_phrases` (policy inferred, attributed per leaf,
  the block switched on by the first phrase, one default camera when
  viewpoints are to vary and none was named, a leaf over a stated
  field dropped with a note), and `VARIATION_INTENT`: a sentence with
  vary/varied/random/randomise/various/assorted that no family matched
  is recorded verbatim and refused by the sampler as
  `randomization.vocabulary`, sentence quoted, on every surface.
* `core/nl/llm_compiler.py`: `LLM_RANDOMIZATION_LEAVES` (hand-listed,
  asserted a subset of the sampler's), `RANDOMIZATION_FIELD_VALUE_SCHEMAS`
  generated from the sampler's table (each leaf admits only its forms
  and vocabulary; every object refuses additional properties), the
  fifth top-level key (the shape sentence now says five keys by
  itself), the parser rails (unknown leaf, entry shape, source, empty
  phrase, form, vocabulary, shape via `policy_problems`), the overlay
  as one attributed Quantity, and the deterministic vocabulary as the
  floor when the model writes no block. The system prompt's
  randomisation paragraph is generated from the compiler's families.
* `core/scene/weather_visuals.py`: the one table (contracts §5.4) --
  Koschmieder `fog_extinction_per_m` (3.912 / (1000 V)), `aerosol`
  (the Mie scale carrying the same extinction alone), `clouds` (one
  layer, stated defaults), `precipitation` / `wetness` and the
  visibility floor, `cloud_drift_mps`, `ev100` per camera from the
  exposure triple, `not_claimed` in every block; `ENGINE_PARAMETERS`
  names the engine parameter per key and `RENDER_FLAGS` the four
  Phase 10 flag names kept for the Look lane. Every row is a pure
  function with its formula in the docstring, re-implemented by the
  tests.
* `core/scene/realised_plot.py`: the picture (`python -m
  core.scene.realised_plot <run dirs> --out realised.png --json
  realised.json`).
* Tests: `tests/test_randomization_policy.py` (20 tests, 29 with the
  parametrised forms: the enum, the
  immutability, the absent-canonical block, every form's support, the
  seeds, the whole contract policy end to end and through YAML, the
  counted refusals, the cap, the sun-floor refusal inside the loop,
  gates, ranges, stated fields, unknown leaves, the window choice, the
  camera group, the realised distribution on fabricated runs and on
  the sampler's own card blocks, the PNG), `tests/test_randomization_prompts.py`
  (a 27-prompt corpus scored as a whole, the page's verdict, the
  byte-identity of prompts with no variation language),
  `tests/test_weather_visuals.py` (9), additions to
  `tests/test_llm_compiler.py` (6, incl. 13 parametrised rails) and
  `tests/test_nl_compiler.py` (2). One pre-existing test moved:
  `test_the_prompt_s_shape_sentence_is_generated_from_the_schema`
  pins "five keys" now (the contract's own change), and
  `tests/test_messages.py` `ALLOWED_FUTURE` drops the three F names
  the code now emits (its own instruction).
* Nine mutation guards in `scripts/mutation_check.sh` ("Phase 2,
  package F"): the refusal recording, the re-draw cap (an exhausted
  slot must refuse, not ship the last draw), the SAMPLED immutability,
  the vocabulary refusal, the validate() gate, the per-draw-index
  seeding, the Koschmieder unit, the compiler's leftover-intent record,
  the LLM tier's shape rail. Each was applied by hand, its test file
  run (fails), the source restored byte-identical (sha256 checked) and
  `__pycache__` purged: 9/9 fire (`scratchpad/pkgF_guards.log`).

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_randomization_policy.py \
        tests/test_randomization_prompts.py tests/test_weather_visuals.py \
        tests/test_randomization.py tests/test_nl_compiler.py tests/test_llm_compiler.py
    ./scripts/mutation_check.sh          # the nine "package F" guards report ok

    # the prompt -> policy -> draw path, refusals by name:
    .venv/bin/python - <<'EOF'
    from core.nl.compiler import compile_prompt
    from core.scenario.randomization import sample_randomization, card_block, RandomizationError
    for prompt in ("fly the a320 at 3000 m in varied weather at different times of day with random viewpoints",
                   "fly the 747 across the rockies", "fly the 747 and vary the moon phase"):
        spec = compile_prompt(prompt)
        try:
            sample_randomization(spec)
            block = card_block(spec)
            print(prompt, "->", {k: block[k] for k in ("visibility_km", "cloud_cover", "precipitation", "hour_local")},
                  "look:", {k: block["look"][k] for k in ("fog_extinction_per_m", "clouds", "wetness")},
                  "refused draws:", len(block["policy_draws"]["refused"]))
        except RandomizationError as exc:
            print(prompt, "-> REFUSED", exc.constraint, "--", exc.message[:90])
    EOF

    # the realised distribution of a set of runs, with the picture:
    .venv/bin/python -m core.scene.realised_plot runs/<campaign>/runs/* --out realised.png --json realised.json

**Not verified here.** Nothing was rendered: which engine component
carries the fog extinction (`FogDensity` in the block's documented
per-metre unit vs the atmosphere's Mie scale), the cloud layer's
altitude and cover as drawn, the wetness scalar and the `ev100`
manual exposure are the Look lane's Gate 6 clauses on the Windows box;
this package records the numbers and names the parameters. No C++ was
touched by F (the flag names and the card block are what both sides
agree on). No live LLM call was made (the fake client only; the
prompt paragraph's effect on a real model is Gate 8.1's measurement).
The `traffic_count` leaf is recorded and not instantiated. Whether
`apply_historical_weather` (webapp) should treat a `sampled` wind like
a `user` one when a sampled `weather_date` fetches ERA5 is a
`webapp/runs.py` decision (today it would overwrite the sampled wind
with the reanalysis wind as a recorded `user` edit).

**Limitations.**

- A drawn `aircraft` does not re-default the cameras' per-airframe
  chase offsets set at compile time (a drawn `preset` does re-default
  the placement); the record says which airframe the offsets were
  defaulted for.
- The Rockies and the Cascades have no bake: the contracts' own policy
  refuses `randomization.location` by name until one lands in
  `core/terrain/glo30.py` `LOCATIONS` and `LOCATION_RANGES`.
- A policy over a prompt that already states the leaf's field refuses
  (top-level) or skips with a note (cameras group) -- never samples over
  a stated value; the compiler drops such leaves with a note before
  the sampler sees them.
- The LLM tier's vocabulary refusal applies only when the model writes
  NO block; a model that maps some leaves and misses an unexpressible
  sentence puts it in `notes` (the prompt tells it to), which is not a
  refusal by name.
- `card.look` is `card.randomization.look` until `card.py` (not F's)
  lifts it; `webapp/server.py` L149 must merge, not overwrite, the page
  dict's `randomization` so the policy survives the page round trip.
- `realised_distribution` bins numeric leaves over the requested
  support when the leaf states one; a lognormal/normal/weibull leaf
  without `clip` is binned over the observed range, so its coverage
  says how the observed spread was filled, not how a tail was.

## P2-B+C/objects -- object identity, the per-frame ground-truth bundle, boxes, depth, occlusion and the second aircraft

**What was measured, and what was defective.** Four things, before
anything was built. (1) The engine mask was a depth-agreement
silhouette (aircraft-alone `SCS_SceneDepth` vs full-scene depth within
5 cm) with exactly one instance id, `ShowOnlyActors = Scenario.Aircraft`
hard-coded, so a second aircraft could never be masked and nothing
distinguished "this object was not drawn" from "this object was not
labelled"; its depth captures inherited the engine's show flags (TSR
by default on the new `DefaultEngine.ini`), so their edge behaviour was
whatever the anti-aliasing history gave. (2) No object in the manifest
had an identity: the exporter's class was the airframe name, KITTI
`occluded` was a dead 3, and `verify.AIRCRAFT_INSTANCE_ID = 1` was an
assumption nothing on the producing side stated. (3) The `applied_*`
intrinsics rode in `render.json` only when the card carried landmarks,
so a verifier projecting a frame without them had to guess. (4)
`simulation_digest` did not drop `taxonomy` (contracts §12): renaming
a class would have split one flight into two dataset sides.

**What was built** (contracts §1, §2.3, §2.4, §3; brainstorm §3.2
option A, §3.3, §3.4, §3.5).

* **Identity** (`core/capture/objects.py`, new). `compose_objects(spec)`
  composes the scene's labelled objects ONCE, from the spec: the
  primary airframe (`aircraft:<fdm>:0`, role `primary`), each traffic
  entry in spec order (`aircraft:<fdm>:<n>`, role `traffic`), then the
  terrain (role `scene`); `int_id` is the composition index from 1 --
  the primary is always 1, so every Phase 10 reader stays true on a
  single-aircraft run -- and `class_id` is the taxonomy position + 1.
  A class the taxonomy does not name refuses `taxonomy.classes`; more
  than 255 objects, or one id composed twice, refuses
  `annotation.identity` (the name is now emitted by code and leaves
  `ALLOWED_FUTURE` in `tests/test_messages.py`). `mesh_sha256` is the
  imported model manifest's digest where this machine has one, null
  where it has not; `licence` is the config's stated licence name.
  The same list rides on the run card (`objects[]`, `taxonomy`), in
  the manifest (`objects[]`, `taxonomy`, `traffic[]`) and in every
  sidecar (`SIDECAR_CONTEXT_KEYS`).
* **Manifest 6** (`core/capture/manifest.py`, `labels.py`,
  `docs/schemas/capture_manifest.v6.schema.json`; v5 stays published
  and a version-5 file still reads and verifies). Per frame,
  `labels.objects[]` carries one record per object in the contracts'
  §3 shape (`object_label_record`): the primary's geometric keys are
  COPIED from the frame's own `labels` so the two cannot disagree; each
  traffic aircraft is projected from ITS cited airframe at its
  scripted state (its own keypoints and 3-D box; `horizon` null); the
  terrain carries nulls, not zeros. New per object: `bbox_2d_hull`
  (the converter's version-3 `mesh_extent_actor_m`, re-based from the
  measured mesh origin onto the CG through the plugin's own
  structural->actor mapping `(-x, y, z) * 2.54`, projected and clipped
  like `bbox_2d`; null with a basis on a machine with no imported
  mesh -- this one), `atmospheric_transmittance` (Koschmieder
  `exp(-3.912/(1000 V) * |CG|)` when the randomisation block states a
  `visibility_km`, `exp(-fog_density * |CG|)` when it states a fog
  density, else 1.0 stated as NOT a measurement), `depth_projected_m`
  (the CG's camera z), `not_claimed` (`subpixel_mask_accuracy_beyond_
  range_m: 8000`, `objects_under_px: 12`, the terrain's "no alone
  pass", and that transmittance is analytic), and a `basis` dict
  naming the sentence behind each derived value. The five
  engine-derived keys -- `bbox_2d_tight`, `visible_fraction`,
  `occluded_by`, `depth_min_m`, `depth_median_m` -- are null with the
  no-bundle basis at build time. `label_conventions` gains `objects`,
  `id_mask`, `alone_pass`, `depth_f32`, `visible_fraction`,
  `bbox_2d_tight`, `bbox_2d_hull`. `labels_sensor.objects[]` maps every
  non-primary object onto the sensor (null boxes for the terrain, so
  the exporter sees "no box" rather than no entry).
* **The post-render step** (`labels.attach_engine_labels(run_dir)`,
  called by `flightsim.capture --render` after the render passes and
  before the sensor post-pass). Reads, per frame the manifest names,
  `frames/<camera>/render.json` and the files ITS record declares --
  the ID image, `_depth.f32` (else the 16-bit PNG at `depth_scale_m`,
  stated in the basis), each aircraft's alone png -- and computes with
  numpy the tight box (pixel (x, y) covers [x, x+1), so the far edges
  are one past the last pixel, in `bbox_2d`'s units), `visible_fraction
  = pixels / pixels_alone`, `occluded_by` (the ids found inside the
  alone footprint, resolved to strings through `objects[]`; an integer
  the list does not name stays visible as `int_id:<n>`), and the depth
  min/median under the mask; writes the manifest and every sidecar
  back with `basis.engine = {files, pixels, pixels_alone, method}`. A
  frame with no bundle keeps its nulls; a manifest below 6 is left
  alone and says so; a depth file of the wrong size refuses rather
  than reshaping. It is the producer of these numbers, not their
  judge: package D re-derives every one from the same files.
* **The second aircraft** (`core/capture/poses.py`,
  `core/scenario/card.py`, `flightsim/capture.py`;
  `FlightSimScenarioWorld.{h,cpp}`, the commandlet). Not a second FDM:
  `solve_traffic_track` solves a position + attitude track relative to
  the primary's recorded telemetry -- `formation` abeam right at
  `range_m` copying the primary's attitude, `crossing` a straight line
  at the primary's mean ground speed heading +90 deg placed so that at
  the run's midpoint the traffic sits exactly `range_m` AHEAD along the
  primary's heading (it crosses the line there), `overtaking` abeam
  right sliding from `range_m` behind to `range_m` ahead; crossing and
  overtaking wings-level, stated on the manifest's
  `traffic[].attitude_basis`. The track is a `PoseTrack` (the camera
  container reused, lens fields zero) and rides on the card as
  `traffic[].poses` in the cameras' block shape, with `cg_actor_cm`
  (the airframe's CG in the actor frame) and the imported mesh
  manifest path. Python refuses `aircraft.mesh` by name for a traffic
  airframe that is not imported, before any flight, with the same
  words the primary gets. `FFlightSimScenarioWorld::ReadCard` parses
  `objects[]` (refusing an `int_id` outside 1..255 or one that names
  two objects, `annotation.identity`), `taxonomy` and `traffic[]`
  (refusing misaligned or non-increasing keyframes); `Populate` spawns
  one bare Movable actor per entry; `Step()` places each on its track
  after the world tick at the FDM's own sim time (linear in position
  and in each Euler angle, clamped to the track's ends with one log
  line) through the SAME mapping the camera track uses --
  `ProjectedToEngine` of `(origin_x + east, origin_y + north, alt)`,
  `FRotator(pitch, yaw - 90, roll)`, actor origin `= CG - R * cg`
  exactly as the FDM actor is placed. The commandlet hangs each
  traffic mesh through `BuildMeshAirframe` (which now tolerates a null
  animator: surfaces undeflected at their hinges) and refuses
  `aircraft.mesh` for an entry with no manifest path.
* **The bundle in C++** (commandlet; UNCOMPILED here). The `-labels`
  pass now writes: `_mask.png` = the ID IMAGE (8-bit, pixel = `int_id`,
  0 background), from a Custom Depth Stencil pass -- every
  `UMeshComponent` in the world gets `SetRenderCustomDepth(true)` +
  `SetCustomDepthStencilValue(int_id)` (an aircraft actor's its own id,
  every other mesh the terrain's; `r.CustomDepth=3` is already in
  `DefaultEngine.ini`), a post-process material
  `/Game/FlightSim/M_CustomStencilID` emits `SceneTexture:CustomStencil`
  as a flat float, and a `SCS_FinalColorHDR` capture reads it back as
  raw floats into an `RTF_R32f` target (the depth pass's own
  readback path); `_class.png` = `class_id` of each pixel's id (0 for
  id 0); `_depth.png` kept and `_depth.f32` new (raw little-endian
  float32, +inf for sky, `static_assert(PLATFORM_LITTLE_ENDIAN)`);
  `_alone_<int_id>.png` per aircraft object (the ID pass with
  `PRM_UseShowOnlyList` on that actor alone). Every label capture --
  depth, ID, each alone -- is configured by one lambda: AntiAliasing,
  TemporalAA, ScreenPercentage, Fog, Atmosphere, VolumetricFog, Bloom,
  MotionBlur, DepthOfField, LensFlares and Translucency show flags off,
  `bAlwaysPersistRenderingState = false`. `render.json` per frame keeps
  every Phase 10 key (the primary's `silhouette_pixels` /
  `visible_pixels` / `occlusion_fraction` now from its alone pass and
  the ID pass) and adds `depth_f32`, `anti_aliasing: "none"`,
  `classes` generated from the card's taxonomy, `method`, `id_source`
  (the card's list, or the Phase 10 default pair when a card carries
  no `objects[]` -- stated, never silent), `unlabelled_geometry_pixels`,
  `non_integer_id_pixels` (readback floats that were not whole
  numbers; an AA-free pass gives 0) and `objects[]` with per-object
  `pixels`, `pixels_alone`, `alone_png`, `visible_fraction`,
  `occluded_by` (integers), `depth_min_m`, `depth_median_m`. The root
  gains `objects[]` and `traffic[]`. `applied_focal_length_mm` /
  `applied_sensor_width_mm` / `applied_fov_deg` / `applied_width_px` /
  `applied_height_px` are written on EVERY consume-poses frame. The
  5 cm depth-agreement mask and its constant are gone.
* **Contract additions stated on the page** (§2.4 and §3 "as landed"):
  the manifest's `taxonomy` and `traffic[]` keys, the card's three
  blocks, the uniform per-object key set with `basis`, the render.json
  `id_source` / pixel counts / root echoes, and the material the ID
  pass needs.

**Tests and guards.** `tests/test_capture_objects.py` (17 tests):
composition stability across two compositions and across a camera
change, primary = 1 and the exact `objects[]` key set; the 256-object
and duplicate-id refusals by name; a class outside the taxonomy;
`resolve_ids`; the crossing track's geometry (at the midpoint exactly
`range_m` ahead along the heading, +90 deg, at the primary's mean
ground speed in the frame -- NOT asserted as the nominal 120 m/s,
because the synthetic track's degrees-to-metres scale is not the UTM
frame's), formation abeam with the copied attitude, overtaking through
abeam at the midpoint; the card block's `cg_actor_cm` against the
plugin's own logged number for the B747; the run card's three blocks
and its byte-identity without them; every manifest-6 record shape, the
primary copied key for key, the traffic's own 37.5 m box, the terrain's
nulls; the taxonomy leaves `simulation_digest` alone while traffic does
not; the hull box from a version-3 manifest (the B747 mesh nose lands
on the labelled nose to 1 cm) and its refusals; Koschmieder from
`visibility_km`, from `fog_density`, and 1.0 stated; a version-5 file
reads, verifies, and `attach_engine_labels` leaves it alone; the
bundle attach on a FABRICATED bundle (an 8-bit ID png with primary 1,
traffic 2, terrain 3 below a horizon row; a float32 depth file; alone
pngs with the primary's footprint grown by 8 px under the traffic; a
render.json naming every file): tight boxes to the pixel, visible
fraction and `occluded_by` against the painted geometry, depth
min/median, the terrain's tight box and depth with NO visible fraction,
provenance files and counts, the sidecar, the v6 schema, idempotence;
no bundle keeps the nulls; a truncated `.f32` refuses; and
`measure_object` by hand on a 6 x 8 array. `tests/test_camera_labels.py`
pins 6 and `(3, 4, 5, 6)`; `tests/test_capture_schema.py` adds five v6
corruptions by path and keeps v5 published. Eight new mutation guards
in `scripts/mutation_check.sh` (the enumerate start; the >255 refusal;
the tight box's far edge; `visible_fraction`; `occluded_by`; the
crossing range; the traffic-without-tracks refusal; the depth-size
refusal) plus the retargeted version-tuple guard: each applied by hand
with the script's own replacement, its test file run, the source
restored byte-identical (sha256) and `__pycache__` purged -- 8 of 8
fire, and the three pre-existing guards on `labels.py` / `manifest.py`
still fire after the edits. Pre-existing tests changed because the
contract changed, and why: `tests/test_dataset.py` and
`tests/test_dataset_formats.py` pinned the exporter's class as the
airframe name (their own comment: "no taxonomy on a v5 run"); a
manifest-6 run names classes from the taxonomy (contracts §2.1), so
they now expect `aircraft` and the six-class list, the byte-identity
pin against the frozen Phase 10 writer runs on a run REWRITTEN to the
version-5 shape (the only input on which that pin has meaning), the
card lists the object's licence beside the config's, and the card
aggregates the per-object `not_claimed` sentences.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_capture_objects.py tests/test_camera_labels.py tests/test_capture_schema.py tests/test_camera_manifest.py
    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/objects_demo --max-previews 0
    .venv/bin/python -c "import json; m=json.load(open('runs/objects_demo/capture_manifest.json')); print(m['manifest_version'], m['objects']); print(json.dumps(m['frames'][0]['labels']['objects'][0], indent=1)[:1500])"
    .venv/bin/python -m flightsim.verify runs/objects_demo      # json_schema PASS against v6; label checks as before
    ./scripts/mutation_check.sh                                 # the eight package-B/C guards are in the last block
    # A spec with traffic (no example ships one yet): add to any example
    #   traffic:
    #   - aircraft: {value: A320, source: user, from: "an A320 crossing"}
    #     track: {value: crossing, source: default, from: documented traffic default}
    #     range_m: {value: 400.0, unit: m, source: default, from: documented traffic default}
    #     livery: {value: default, source: default, from: documented traffic default}
    # and run the same capture: card.json gains objects[]/taxonomy/traffic[], the manifest a second aircraft record per frame.

**Not verified here (no engine in this container).** Every line of
C++ in this package is UNCOMPILED: `FFlightSimScenarioWorld::ReadCard`
/ `Populate` / `ApplyTrafficPoses` / `Step`, `BuildMeshAirframe` with a
null animator, the stencil assignment, the ID captures and their show
flags, the per-frame bundle, the applied-intrinsics move. The first
Windows build verifies, in this order: (1) `scripts/ue_create_materials.py`
must gain `M_CustomStencilID` (this package could not edit that file):
`unreal.Material` at `/Game/FlightSim`, `material_domain =
MaterialDomain.MD_POST_PROCESS`, `blendable_location =
BlendableLocation.BL_REPLACING_TONEMAPPER`, one
`MaterialExpressionSceneTexture` with `scene_texture_id =
SceneTextureId.PPI_CUSTOM_STENCIL` connected to `MP_EMISSIVE_COLOR`;
until it exists `-labels` refuses by name and renders nothing under an
ID it did not measure; (2) render one frame with `-labels` and check
`frame_0000_mask.png` holds only the card's ints (`numpy.unique` ==
a subset of `objects[].int_id` plus 0) and `render.json`
`labels.non_integer_id_pixels == 0`; (3) `frame_0000_depth.f32` is
`width*height*4` bytes and `numpy.fromfile(..., '<f4')` under the mask
agrees with the 16-bit PNG to 0.1 m; (4) `frame_0000_alone_1.png`
covers `_mask.png == 1` (the primary's alone footprint contains its
visible pixels), and with a traffic spec `_alone_2.png` exists and the
primary's `occluded_by` lists it on the frames where the traffic
crosses in front; (5) the traffic actor's placement: overlay the
manifest's traffic CG (project `frames[i].labels.objects[1]
.bbox_3d_camera.cg_m`) on the beauty frame and look -- a mirrored bank
in a formation track would mean the `FRotator` roll sign differs from
the camera director's convention (same mapping, unmeasured for an
aircraft); (6) `python -m flightsim.verify` after `attach_engine_labels`
ran: `label_files` / `mask_containment` / `depth_range` PASS as before
(the primary is still 1), and package D's checks grade the new record.
Also not verified: that `SCS_FinalColorHDR` with a replacing-tonemapper
blendable returns the stencil value unscaled by exposure on 5.7 (the
`non_integer_id_pixels` count and D's `mask_integers_only` are the
measurements); the alone pass with `PRM_UseShowOnlyList` rendering the
custom-depth pass for the listed actor only.

**Limitations.** Buildings, vegetation and water are taxonomy classes
with no producer of instances; `cloud` writes no ID. Every non-aircraft
mesh (terrain, the flat ground plane, the tornado funnel) carries the
terrain's id -- "terrain or other", as the Phase 10 class string said.
The terrain gets no alone pass, so its `visible_fraction` is null by
construction. `atmospheric_transmittance` is analytic along the CG ray
(no per-pixel fog, no clouds, no precipitation) and is 1.0 with a
stated basis when the spec states neither a visibility nor a fog
density -- the render host's default fog is NOT modelled in it. The
hull box needs a version-3 mesh manifest on the producing machine;
this clone has none, so every hull box it writes is null with the
basis. Crossing and overtaking traffic fly wings-level with no
dynamics, no collision avoidance and a ground speed equal to the
primary's mean; formation copies the primary's attitude. The
interactive host (`BuildInto`) does not move traffic (only `Step()`
does). `webapp/static/index.html` still hard-codes the v5 schema link
(not this package's file; `frames.html` builds it from the version).
`flightsim.capture` solves traffic tracks but no committed example
carries a `traffic` block yet. The C++ writes the depth file on the
assumption every UE target is little-endian (asserted at compile
time). `mask.png` now carries EVERY int_id, so on a single-aircraft
run its terrain pixels are 2 where Phase 10 wrote 0.

## P2-A/render-flags -- one render-command builder for the CLI and the web app

**What was built.** Measured before this item: the CLI's `--render`
(`flightsim/capture.py`) and the web app's `RunManager._render`
(`webapp/runs.py`) assembled the FlightSimRender commandlet's flags by
hand, in two files, and disagreed. The web app passed `-shot=showcase
-fps= -width= -height=`, the harness's noon look and `-mesh=`; the CLI
passed `-labels` and (since the placeholder rule) `-mesh=`, but no look
unless the randomisation block was on, and no size; NEITHER passed
`-deterministic`, the one flag Gate 10-R proves the frame digests need.
Nothing compared the two lists, so a flag one of them forgot was
invisible (the subsystem maps count thirteen hand-built commands in
all; these two are the ones labelled data comes through). Now:

* `core/render/flags.py` (new package `core/render/`): `render_flags(...)`
  returns the ORDERED argument list after the editor/project/`-run`
  tokens -- `-scenario= -frames= -Visual -shot=showcase <preset camera
  flags> -fps= -width= -height= <look> <launcher tokens> <trailing>
  <extra> -labels -linear -deterministic -GeorefTerrain -terrain=
  -imagery= -mesh= -telemetry=` -- with the terrain, imagery, mesh and
  telemetry tokens present only when given, the void tier stripped of
  scene and sun, a partial look completed from `DEFAULT_LOOK` key by
  key, and every opt-in switch emitted at most once (the web app's loop
  states `-labels` through `extra`). `for_wrapper(flags)` drops exactly
  what `scripts/render_ue_scenario.ps1` writes itself (`-scenario=
  -frames= -camera-index= -telemetry=` and the launcher tokens).
  The builder touches no filesystem and runs no subprocess.
* `flightsim/capture.py` builds its wrapper command from
  `for_wrapper(render_flags(...))`; `webapp/runs.py::_render` builds its
  editor command from `render_flags(...)`. A consume-poses camera pass
  (the one whose pixels are the dataset; recognised by `-camera-index=`
  in `extra`) gets `-deterministic`; the legacy single pass and the
  throw-away solve pass stay byte-identical (no `-labels`, no
  `-deterministic`, preset camera flags kept).
* `tests/test_render_flags.py` (10 tests): compiles one spec
  (`examples/cameras_multi.yaml`), drives BOTH code paths with
  `subprocess.run` intercepted, and asserts the two flag LISTS are
  identical apart from the launcher-owned tokens (and, separately, the
  sets), and that both carry `-mesh=<the same path>`, `-labels`,
  `-Visual`, the four look flags and `-deterministic`. Also pins the
  web app's camera-less list against the recorded expectation, the
  solve pass gaining nothing, `DEFAULT_LOOK` and the size constants
  equal to `showcase_matrix`'s, the void tier, `for_wrapper`, and the
  once-only switches.
* Mutation guard: `scripts/mutation_check.sh` -- "the render builder
  forwards -mesh= to both callers" (`if mesh is not None:` -> `if
  False:`). Confirmed by hand: 4 of 10 tests in
  `tests/test_render_flags.py` fail under the mutation; the file was
  restored byte-identical (sha256 checked) and `__pycache__` purged.
* Contracts §9.1 records the four departures from the page: the module
  name and signature; the launcher tokens inside the list; the CLI
  taking the web app's default look (and `-shot -fps -width -height
  -deterministic`) where it took the commandlet's defaults before; and
  the web app's consume-poses pass dropping its inert `-chase=`/`-camera=
  chase`, which the one-builder test caught as the only remaining
  difference.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_render_flags.py
    .venv/bin/pytest -q -p no:warnings tests/test_camera_spec.py tests/test_camera_cli.py tests/test_randomization.py tests/test_webapp_capture.py tests/test_webapp.py tests/test_powershell_scripts.py   # 317 passed here
    ./scripts/mutation_check.sh          # "ok  the render builder forwards -mesh= to both callers"

To see the two commands side by side without an engine, run the first
file with `-k same_flags -s`: the CLI's wrapper command and the web
app's editor command are captured from the intercepted `subprocess.run`
and the assertion message lists whatever differs.

**Not verified here.** No engine on this platform, so: that the
commandlet accepts the combined list on a real pass (every token is one
it already parsed for one caller or the other; `-shot=showcase` is not
a shot the commandlet distinguishes from its default, `-width/-height/
-fps` are overridden by the card's camera under consume-poses -- both
by reading of `FlightSimRenderCommandlet.cpp`, not by a render); that
dropping `-chase=`/`-camera=chase` from the consume-poses pass leaves
the pixels identical (the code replaces the chase placement with the
track's first pose before the warm-up captures -- by reading); that the
CLI's frames under the noon look match the web app's for the same spec
(the first Windows render of one spec through both paths is the
measurement; `render.json` records the sun either way); that
`render_ue_scenario.ps1` forwards the longer list to every camera pass
(it forwards `$args[2..]` verbatim; `tests/test_powershell_scripts.py`
reads the script, nothing runs it here). No C++ changed.

**Limitations.** The builder owns the flag list, not the placeholder
refusal: `flightsim/capture.py` still imports
`webapp.runs.refuse_placeholder_mesh` (the CLI depending on the web
layer, critique) -- that block was outside this item's files and is an
open item for whoever owns it. The eleven experiment builders
(`gate6_visual.py`, `gate10_render_repro.py`, `showcase_matrix.py`, ...)
still build their own commands; contracts §9 says they migrate next.
The `.sh` wrapper forwards nothing (two arguments, macOS only), so off
Windows the forwarded flags reach no engine -- the wrapper refuses
`ue.platform` first, as before. `webapp/runs.py` keeps its now-unused
`TIME_OF_DAY` / `VISIBILITY` imports (the import block is not the
method this item owned). The `.ps1`'s header comment still says
`-width= -height=` are not passed on the camera path; they now are, and
are inert there -- the comment is stale, the script's behaviour is not.

## P2-G/campaign -- campaign execution at scale: the campaign object, the index-seeded worker pool, the ledger-derived truth

**What was built.** Measured before this item: the batch runner
(`core/dataset/batch.py`) submitted every case to a thread pool up
front, appended rows in completion order, had no state machine, no
pause/cancel, no watchdog, no disk budget, aborted the whole build on
the first refused draw, and its "two workers give the same rows" test
compared only counts (subsystem map, known defects). `grep campaign`
found nothing. Now:

* `core/campaign/` (new package): **`campaign.py`** -- `Campaign.create
  (prompt, answers, images, seed, policy, out, format, workers, ...)`,
  `.open`, `.plan()`, `.sample(n)`, `.run(workers)`, `.pause()`,
  `.resume()`, `.cancel()`, `.status()`, `.report()`, `.export(format)`;
  the state machine `planned|running|paused|failed|done|cancelled` with
  its transition table (`TRANSITIONS`; an illegal move refuses
  `campaign.state`); `campaign.json`, `control.json` and `report.json`
  as contracts §6.1 / §6.3, all written atomically. **`ledger.py`** --
  the append-only, fsynced, truncation-tolerant `ledger.jsonl` keyed
  on the slot index; `summarise(rows)` computes progress, yield,
  refusals by name, bytes per case and the next index FROM THE ROWS,
  and `comparable(rows)` strips timing and machine paths for the
  cross-worker comparison. **`workers.py`** -- `case_seed(index,
  campaign_seed)` = `SeedSequence([index, campaign_seed])` folded;
  `build_case(index, record)` plans the run seed from the index (a
  stated seed is kept), sets the block's seed to the campaign seed and
  runs the one sampler with `draw_index=index`; `run_with_watchdog`
  kills a capture that writes nothing for N seconds; `run_index` is
  the picklable worker (spawn start method) that writes `runs/<case_id>/
  spec.yaml`, runs the `flightsim.capture` CLI (the batch's own
  `capture_command`), verifies through the batch's `case_row`, and
  returns one row -- or a `refused` row by the sampler's name, or a
  `campaign.duplicate_case` refusal when the ledger already holds that
  spec. **`report.py`** -- `build_report` (yield, coverage and realised
  distributions via `core.scenario.randomization.realised_distribution`
  over the verified cases, refusals by name split into refused slots
  and refused attempts inside successful draws, timing, disk) and
  `render_report` in words.
* Execution is in ROUNDS: the indices a round runs are decided from
  the ledger when it starts, `workers` cases are in flight at a time
  pulled from that list in index order, every completion appends its
  row and then polls `control.json` and re-checks the disk budget
  (`bytes_per_case` measured from completed run directories times the
  cases still needed, against `min(budget, free)`; refused
  `storage.budget_exceeded` before a round and after every case;
  unmeasured is no claim). A campaign ends `done` in exactly one place:
  when the ledger's verified frames reach the target. Below it, it
  ends `failed` with `campaign.target_unreachable` and the reasons
  (refused slots by name up to `max_refused_slots`, failed captures,
  captured-but-unverified cases, two rounds without progress).
* `flightsim/campaign.py` (new CLI): `python -m flightsim.campaign
  "<prompt>" --images N --out DIR [--workers W] [--seed S] [--format
  coco] [--tier regex|llm] [--answer id=text] [--disk-budget-gb G]
  [--stall-minutes M] [--render] [--plan] [--sample N] [--export]`; on
  an existing `--out`: `--resume`, `--pause`, `--cancel`, `--status`
  and `--report`. `--export` exports the verified runs only in the
  invocation that runs the campaign to `done` (the creating one, or a
  `--resume` that finishes it): measured at 7b0a39a, `--out DIR
  --export` alone is refused `campaign.arguments` (its sentence lists
  the five existing-campaign actions and not `--export`), `--status
  --export` and `--report --export` print and return before the export,
  and `--resume --export` on a done campaign is refused
  `campaign.state`. A campaign already done exports through
  `python -m flightsim.export DIR/runs --out ... --format ...` (the
  runs directory; the campaign directory itself is refused
  `export.runs`). Making `--export` an existing-campaign action is an
  open item on `flightsim/campaign.py`. Exit 0 done, 1 ended otherwise,
  2 refused before anything ran; refusals print `REFUSED -- <name>:`.
* `core/dataset/batch.py`: `run_case` factored into `run_capture`
  (the subprocess) and `case_row` (ok/verify/verification.json), which
  the campaign's worker reuses so the two ledgers agree key for key;
  `CAPTURE_OPTIONS` gains `terrain`/`synth_terrain` (contracts §6.1) so
  a mountain case can run through either runner. `flightsim.batch`'s
  argv, rows and tests are unchanged (14 + 41 tests green).
* `tests/test_campaign.py` (13 tests, two of them real headless
  campaigns): the transition table; every argument and plan refusal by
  name (`campaign.arguments`, `export.format`, `randomization.vocabulary`,
  `randomization.location`, the validator's `airspeed.*`); seeds by
  index with the derivation RE-IMPLEMENTED in the test from
  `numpy.random.SeedSequence`; previews that never regress a row; a
  campaign whose every capture fails ends `failed` /
  `campaign.target_unreachable` with each slot retried exactly once; a
  hand-written ledger (with a killed half-line) read by a FRESH object
  reports the truth in `status()`, `report()` and `plan()`; the disk
  budget refused after the first measured case and again before a
  resume, then lifted and resumed to done; the watchdog on a sleeping
  process and a writing one; pause and cancel through `control.json`
  between cases with the resumed case set equal to the uninterrupted
  one; a prompt with nothing to vary refusing duplicate slots by name;
  the CLI's exit codes and words; report and export; and **the exit
  criterion**: the same 250-image campaign run with `workers=1` and
  `workers=2` (spawned processes) has identical case ids, seeds,
  sampled values, `spec_digest` / `simulation_digest` / `output_digest`
  per manifest, identical `randomization` blocks, and an identical
  ledger apart from timing and paths.
* Four mutation guards in `scripts/mutation_check.sh` ("Phase 2
  package G"): done regardless of yield; seeds by completion order
  (the number of run directories on disk when the worker starts --
  identical to the index at one worker, not at two); the budget never
  enforced; `status()` reading nothing from the ledger. Confirmed by
  hand: 7, 1, 1 and 5 tests of `tests/test_campaign.py` fail
  respectively; each file restored byte-identical (sha256 checked) and
  `__pycache__` purged.
* Contracts §6.3 states every shape decision and departure: the
  ledger keyed on `index`, `rendered` = captured but not verified, the
  compiled `spec` carried in `campaign.json`, rounds rather than a
  streaming queue, the frames-per-case estimate/measurement rule, the
  three new refusal names `campaign.state`, `campaign.arguments`,
  `campaign.duplicate_case`.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_campaign.py                 # 13 passed, ~40 s
    .venv/bin/pytest -q -p no:warnings tests/test_dataset.py tests/test_dataset_formats.py tests/test_randomization_policy.py   # the suites the factoring touches
    ./scripts/mutation_check.sh          # the four "Phase 2 package G" guards report ok

    # a real campaign, headless, no engine: three cases of ~96 frames, two workers
    .venv/bin/python -m flightsim.campaign \
        "fly the a320 at 3000 m for 10 seconds in varied weather at different times of day, chase view" \
        --images 250 --seed 7 --workers 2 --out runs/campaigns/demo
    .venv/bin/python -m flightsim.campaign --out runs/campaigns/demo --report      # in words
    .venv/bin/python -m flightsim.campaign --out runs/campaigns/demo --status      # the ledger's numbers
    .venv/bin/python -m core.scene.realised_plot runs/campaigns/demo/runs/* --out realised.png   # the picture (package F's tool)

    # the exit criterion by hand: the same campaign at one worker, then compare
    .venv/bin/python -m flightsim.campaign "<the same prompt>" --images 250 --seed 7 --workers 1 --out runs/campaigns/demo1
    .venv/bin/python - <<'EOF'
    from core.campaign import Campaign
    from core.campaign.ledger import comparable
    a, b = Campaign.open("runs/campaigns/demo"), Campaign.open("runs/campaigns/demo1")
    print("identical:", comparable(a.ledger.rows()) == comparable(b.ledger.rows()))
    EOF

    # refusals by name, before anything runs
    .venv/bin/python -m flightsim.campaign "fly the 747 and vary the moon phase" --images 10 --out runs/campaigns/x --plan   # REFUSED -- randomization.vocabulary
    .venv/bin/python -m flightsim.campaign "<prompt>" --images 250 --disk-budget-gb 0.001 --out runs/campaigns/y            # storage.budget_exceeded after the first measured case

(The JSBSim banner lines on stdout come from the sampler's per-attempt
trim check; they are the FDM's own and not the campaign's.)

**Not verified here.** No engine on this platform, so: that
`--render` campaigns draw pixels (each case's `flightsim.capture
--render` refuses `ue.platform` here and the row records `drawn:
false`); the `rendered` status on a real render; `bundle_digest` over
a real `render.json` (null on every row here); the watchdog against a
stalled commandlet (measured against a sleeping Python process only);
the throughput knee at 1/2/4 engine instances on one GPU (brainstorm
§6 says measure it on the target card; `workers` is a cap, nothing
here chose a value); Windows Error Reporting suppression; the
`spawn` pool on Windows itself (it is the only start method there and
the code uses no fork-only path, but this container ran it on Linux
where `spawn` was explicitly selected). The LLM compile tier
(`--tier llm`) falls back to regex here (no provider) and records that
it did; no LLM-compiled campaign has run. `terrain`/`synth_terrain`
capture options are forwarded by `capture_command` (asserted by no
test that flies one through a campaign).

**Limitations.** Frames per case are an estimate for the first round
(recorder cadence 0.1 s; the estimate said 101 where the measurement
said 96) and measured after -- a campaign may run one round more than
the minimum, never fewer frames than the target. Failed captures are
retried once in all (`MAX_ATTEMPTS = 2`) and a captured-but-unverified
case is never retried (batch semantics), so a campaign whose cases
verify below the target ends `failed` and says why; nothing here
diagnoses the verification. A duplicate slot from a prompt with
nothing to vary is only known once the worker has built it (cheap:
sampling, no capture, when the ledger already holds the case id;
when two were in flight together the second is run and then refused
on collection). The ledger's raw line ORDER still follows completion
in the pool; `comparable()` is the stated comparison. The web app's
compile-time planners are not applied (contracts §6.3, package H's
core-level compile-and-plan); `verification.json` is still written
non-atomically by `core/capture/verify.py` (not this package's file).
The report's `coverage` is over 8 bins per numeric leaf with `k = 1`,
package F's default; three cases cover 30 % of the requested bins,
which the words say plainly. No picture is drawn by this package;
`core.scene.realised_plot` is the one for these runs.

## P2-Look/2 -- the visual scene, the beauty/label capture settings and the camera exposure model (C++ UNCOMPILED here)

**What was measured, and what was defective.** (1) No C++ read the
card's look block: package F's `randomization.look` (fog extinction,
clouds, precipitation, drift, EV100) was written to every card with a
policy and consumed by nothing; the scene was lit from the four Phase 10
flags only, and a frame carried no record of any renderer switch
(`render_settings` did not exist, so the Look/1 INI settings were
asserted, never read back). (2) The legacy `-camera=shoulder` path
span-scaled `ShoulderOffsetMetres` with a 1.3 m z floor
(`FlightSimRenderCommandlet.cpp`) while `core/capture/poses.py` applies
`SHOULDER_OFFSET` (-6, -0.5, 1.6) m unscaled from the CG -- the anchor
agreed since eb5c71d, the magnitude did not (critique); and the
director's chase/wingman defaults (-60, 0, 12) / (-15, 25, 0) disagreed
with Python's (-110, 0, 12) / (-45, 180, 0) wherever no flag overrode
them. (3) The georeferenced terrain was one procedural section capped at
701 vertices a side: a 30 m GLO-30 raster rendered at 60 m posting, and
the posting was a comment, not a recorded number. (4) `-exposure-bias`
was a probe-tuned stop count; the spec-8 exposure triple reached no
pixel. (5) The look's `aerosol` row, applied literally, evaluates to a
Mie scattering scale in the HUNDREDS for the Phase 10 default fog
(`aerosol_scale(visibility_km_for_extinction(0.0025))` = 564): the fog
already carries that extinction, and driving both whitens the sky.

**What was built.**

- `FlightSimVisualScene.{h,cpp}`: a `UVolumetricCloudComponent`
  (Engine module, `Components/VolumetricCloudComponent.h`) from the
  first look cloud layer -- `SetLayerBottomAltitude(base_m/1000)`,
  `SetLayerHeight((top-base)/1000)` above the scene's ground datum
  (engine Z=0 = the spec's `terrain_elevation_m`, stated as
  `base_datum`), the engine's default cloud material through a dynamic
  instance whose first scalar parameter containing "cover" carries the
  cover fraction (the name found, or `"absent"`, is recorded; a missing
  material is refused by name `look.clouds`), cloud shadows on the sun
  (`SetCastCloudShadows`, `SetCloudShadowStrength 1`); Sky Atmosphere
  `SetMieScatteringScale` ONLY under `-aerosol=` (the card's value is
  recorded as `card_aerosol`, departure 2 in contracts 10.1); height fog
  density from the look's `fog_extinction_per_m` (the card overrides
  `-fog-density`; whether `FogDensity` IS a per-metre extinction is the
  new Gate 6 clause's measurement, not a claim); `-precip=rain|snow` /
  `look.precipitation` sets a `Wetness` scalar on the georeferenced
  terrain's material instance and records whether the material exposes
  one (`wetness_parameter`); the sun is the existing light; `-stars`
  and `-moon` are accepted and recorded `"not modelled"`; cloud drift is
  recorded with `applied: false`. Every row lands in `LookApplied`, which
  the commandlet writes as `render.json.look_applied` with its `source`
  (`card.look` | `card.randomization.look` | flags) and the list of
  probe overrides.
- Physical exposure: `ApplyPhysicalExposure(Capture, N, t, ISO)` sets
  `AEM_Manual`, `AutoExposureApplyPhysicalCameraExposure = 1`,
  `CameraShutterSpeed = 1/t`, `CameraISO`, `DepthOfFieldFstop` and pins
  the bias to 0; `ExposureValue100` re-implements
  `log2(N^2/t * 100/ISO)`. The commandlet runs it when the consumed
  camera carries `cameras[N].exposure {aperture_f, shutter_s, iso}`
  (a partial triple is refused by name `camera.exposure`), else applies
  `look.ev100[camera_id]` through N=1, ISO=100, t=2^-EV100, else the
  Phase 10 bias path unchanged; `-AutoExposure` skips all three.
- `render.json.render_settings` (root, every run): the Look/1 console
  variables READ BACK through `IConsoleManager` (value or `"absent"`),
  the AA method per capture from each capture's own show flag plus the
  `r.AntiAliasingMethod` name (0 none / 1 FXAA / 2 TAA / 3 MSAA / 4 TSR;
  a label capture whose flag is found on is written as `DEFECT:`), the
  beauty capture's show flags as booleans, `capture_size_px`,
  `exposure_mode` (`auto` | `manual_bias` | `manual_ev100`),
  `exposure_source`, `ev100`, `exposure_bias`, the extended-luminance
  CVar, `rhi`, `shader_platform`, the deterministic pin state, and the
  three preset offsets as flown. `scene.exposure` says
  `manual, EV100 14.97 (physical camera)` on the physical path and keeps
  its two old spellings otherwise (the Gate 6 control check still
  matches `auto`).
- Label passes: unchanged in structure; `SetCloud(false)` joins the
  contracts section 1 show-flag list (recorded there).
- `core/capture/exposure.py`: `ev100` (refuses `camera.exposure` by
  name), `PRESET_DEFAULTS` restating the six presets' daylight triple
  (never importing `core.scenario.camera`; the test is where the two
  tables meet), `shutter_for_ev100` (the inverse the commandlet uses),
  `describe`, the `exposure_mode` spellings.
- Terrain: `BuildGeoreferencedTerrain` builds the decimated grid at the
  smallest stride whose triangle count fits `TerrainTriangleBudget`
  (4 M; a 1276x905 raster fits at stride 1 = native 30 m posting) and
  cuts it into `UProceduralMeshComponent` tiles of at most 256 vertices
  a side (edges shared, normals from the full raster, one component per
  tile so each has its own bounds) under one `TerrainGeoreferenced`
  root; the vertex-colour palette and the imagery drape are untouched
  (`ClassifyVertex` and the Gate 6 `BuildTerrainInstance` are
  byte-identical to HEAD, diffed). `scene.terrain_posting_m`,
  `terrain_stride`, `terrain_tiles`, `terrain_triangles` record what was
  achieved. The label pass needs no change: it stencils every
  `UMeshComponent` of every actor.
- Preset parity: the span scaling is gone from the shoulder block
  (`render_settings.cockpit_offset_m` records the unscaled body offset);
  `FlightSimCameraDirector.h` defaults are `FALLBACK_CHASE_OFFSET` and
  `WINGMAN_OFFSET`, pinned to the Python constants by a test that reads
  the header text. The commandlet's shot constants (-170 / -400 m) and
  `-chase=` still override the chase as before, so the header default
  reaches the interactive host and any caller that does not override.
- `experiments/gate6_visual.py`: four look clauses (`look_clauses`),
  each PASS / FAIL / NOT RUN with its measurement stated, rendered by
  `--look` from `LOOK_RUNS` (one switch per control, gotcha 6) and
  graded whenever their directories exist: the cloud base bracket (a
  layer 300 m above the 300 m flight may change the sky band only; one
  300 m below, the ground band only), extinction vs `visibility_km`
  (the ratio at Koschmieder fog for 50 km and 10 km, the constant
  re-implemented), the wet-surface null test (terrain band changes, sky
  band must not, `wetness_parameter` must not be absent), and exposure
  at -12 deg sun (frames not black, sky band holds over the doublet).
  A FAIL counts against the gate only when the clause ran.
- Tests: `tests/test_exposure.py` (hand-computed 14.966, ISO stops,
  refusals by name, the two tables, the inverse, the C++ expression
  pinned) and `tests/test_gate6_visual.py` (each look clause against a
  frame built to lie, NOT RUN with measurement when unrendered, the
  controls change one switch each, and the engine-source pins: director
  defaults = Python constants, no span scaling, every contracts-1 show
  flag off in `ConfigureLabelCapture`, `render_settings` reads every
  contracted switch with `"absent"` as the miss value, the commandlet
  reads exactly `weather_visuals.ENGINE_PARAMETERS`' keys, the terrain
  budget and posting record).
- Ten `mutate` guards in `scripts/mutation_check.sh` (EV100 with ISO the
  wrong way up; the chase default back to -60; span scaling back; the
  label cloud flag on; a missing CVar recorded as 0; a look key the
  producer never writes; each of the four look clauses weakened), each
  applied by hand in this container, its test file run, the file
  restored byte-identical (sha256 checked) and caches purged: all ten
  fired.

**How to demonstrate (any platform).**

```
.venv/bin/pytest -q -p no:warnings -o addopts= tests/test_exposure.py tests/test_gate6_visual.py
.venv/bin/python -c "from core.capture.exposure import ev100, describe; print(ev100(8, 1/500, 100)); print(describe(8, 1/500, 100))"
.venv/bin/python experiments/gate6_visual.py --skip-render --out /tmp/no_such_gate   # blocked without an editor; the clause list prints NOT RUN with each measurement
.venv/bin/python -c "import experiments.gate6_visual as g; [print(c.render()) for c in g.look_clauses(__import__('pathlib').Path('/nonexistent'))]"
bash scripts/mutation_check.sh          # the ten Look/2 guards report ok
git diff HEAD~1 -- ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimVisualScene.cpp | grep -c '^-.*ClassifyVertex'   # 0: the palette is untouched
```

**Windows probes (one control render per switch, the gotcha 6 pattern;
each is a `--look` control in `LOOK_RUNS`).** After `scripts\build_ue.ps1`
and `ue_preflight.ps1` on 5.7, from the repo root:

```
.venv\Scripts\python experiments\gate6_visual.py --look --out runs\gate6_57
```

renders the Phase 10 six plus `cloud_above`, `cloud_below`,
`cloud_control`, `visibility_clear`, `visibility_hazy`, `wet`,
`wet_control`, `night`, then prints the four look clauses with numbers.
Look at `runs\gate6_57\<name>\frame_0000.png` beside its control (gotcha
12) and at `render.json` -> `look_applied` (`clouds.cover_parameter`,
`precipitation.wetness_parameter`: if either says `absent`, the material
is the finding, not the clause) and `render_settings.console` (every
value must be the INI's, not `absent`; `anti_aliasing.beauty` should say
`TSR` and `.labels` `none`). Exposure parity: render one consume-poses
card twice, once with the bias path and once with `look.ev100`, and
compare the sky band mean; a difference of more than a few counts at the
same EV is the calibration constant (extended range) to read off
`render_settings.extend_default_luminance_range`. Terrain: a
georeferenced render's `scene.terrain_posting_m` must equal the raster's
pixel size (30) and `terrain_tiles` about `ceil(1275/255) *
ceil(904/255)` = 20 for the Matterhorn bake; the ridgelines in the frame
against the 5.5 60 m-posting control are the picture. A 5.7 first build
also re-checks these API assumptions, in this order: the
`Components/VolumetricCloudComponent.h` include and the public `Material`
member; `SetLayerBottomAltitude` / `SetLayerHeight`;
`UDirectionalLightComponent::SetCastCloudShadows` /
`SetCloudShadowStrength`; `USkyAtmosphereComponent::SetMieScatteringScale`;
`UMaterialInterface::GetAllScalarParameterInfo(TArray<FMaterialParameterInfo>&,
TArray<FGuid>&)`; `FEngineShowFlags::Cloud` / `SetCloud`; the
`FPostProcessSettings` physical-camera fields (`bOverride_AutoExposureApplyPhysicalCameraExposure`,
`CameraShutterSpeed`, `CameraISO`, `DepthOfFieldFstop`);
`LexToString(GMaxRHIShaderPlatform)` from `RHI.h`;
`FJsonObject::HasTypedField<EJson::Object>`.

**Not verified here.** No engine: none of the C++ compiles or renders
in this container. Not one look clause has run -- each reports NOT RUN
with its measurement; whether `FogDensity` scales as an extinction,
whether the default cloud material exposes a cover parameter (and by
what name), whether `M_VertexColor` / `M_TerrainImagery` expose a
`Wetness` scalar (they were built by `scripts/ue_create_materials.py`
without one, so the first render is expected to record `absent` and the
wet clause to FAIL by name until the material gains the parameter),
whether the engine's EV100 lands within a stop of the recorded number,
what a 2.3 M-triangle tiled procedural mesh costs per frame, and
whether the cloud layer's base sits where `base_datum` says, are all
first-render measurements on the Windows box. The `-precip` particle
system is not built (stated in every record). The engine-source tests
measure text, which is the only measurement possible here.

**Limitations.**

- `core/capture/poses.py` does not write `cameras[].exposure` onto the
  run card (not this stage's file), so today the physical path is
  reachable only through `look.ev100` (written when a policy exists).
  One line in the card writer makes the triple path live.
- `core/render/flags.py` does not emit the six probe flags and no Python
  caller passes them: the look reaches production renders through the
  card, the probes through the harness. A card's `aerosol` is never
  applied (departure 2).
- One cloud layer is drawn; the commandlet's shot constants still
  override the chase offset (-170 / -400 m), so the header default
  reaches only callers that do not set it (the interactive host sets its
  own -170 m in `FlightSimInteractiveMode.cpp` L198).
- Sections in one procedural mesh do not frustum-cull; one component per
  tile does, at the cost of duplicated edge vertices (< 1 %). The
  Landscape import path (`core/terrain/landscape.py`) stays the next
  step; VSM on a Movable procedural mesh remains whatever the renderer
  does with it, read back in `render_settings.console`.
- Recorded, not patched (vendored plugin):
  `UJSBSimMovementComponent::UpdateLocalTransforms` pushes
  `StructuralToBody(0)` -- a BODY-frame vector -- through the
  structural->actor matrix to form `CGLocalPosition`; x and z come out
  right by two cancelling sign flips, y would be sign-wrong for a
  non-zero CG y. Every staged airframe has y = 0.
- `tests/test_platform.py::test_no_text_io_without_utf8_encoding` fails
  on this tree for `core/campaign/campaign.py`, `tests/test_annotation_gates.py`
  and `tests/test_campaign.py` -- files of parallel packages, not this
  stage's; every text I/O this stage added states `encoding="utf-8"`.

## P2-D/gates -- the annotation quality gates: seven checks over the ground-truth bundle, refusals by name, mutation guards that fire, visual sheets

**What was measured, and what was defective.** Four things, before
anything was built. (1) `scripts/mutation_check.sh` carried an aliased
guard: the 12-space `'            if gap > tol:'` of the chase-station
entry is a SUBSTRING of the 16-space world-anchored clause 46 lines
earlier in `verify.py`, and `mutate()` does `str.replace(old, new, 1)`
-- so the chase entry re-disabled the tower clause, reported "ok" for
the tower test going red a second time, and the chase clause was never
tested by the script at all. Both entries now carry their clause's own
preceding lines (`math.dist(camera, expected)` vs `math.dist(station,
offset)`) and each was confirmed to fire against its own clause. (2)
The contract's "mask centroid vs projected CG <= 2 % of the span"
fails a PERFECT silhouette: a hull is not centred on its CG (the 747's
box centre is 4.8 m above it, 6 % of the span from behind) and
perspective does not preserve area centroids (at the 185 m wingman slot
the near end of a 70 m box projects 1.5x the far end, 5.6 % of the span).
Measured on the fabricated bundle before the check was written down;
the check grades the two box centres (contracts §4 "as landed"). (3)
"depth_min / depth_median vs the projected CG depth at 1 % + 2 m"
cannot hold: from behind, the visible surface of a 70 m airframe is
37 m nearer than its CG; a hull box's nearest corner is up to 0.75 L
nearer than any airframe point on a diagonal view. The clauses that
hold on any view and still catch a 2 % scale are listed on the page.
(4) A blur of an 8-bit ID image whose ids are 1, 2, 3 produces only
1, 2, 3: the histogram check the contract describes cannot see it; the
class image and the engine's own `non_integer_id_pixels` can.

**What was built** (contracts §4, §11; brainstorm §3.6).

* **Seven checks in `core/capture/verify.py`**, appended after
  `depth_range` and before `sensor_undistortion`, each PASS / FAIL /
  NOT RUN, each FAIL carrying its catalogue name in the new
  `Check.failure` field (`verification.json` gains `"failure"` on FAIL
  only; every reader takes it by key):
  `mask_integers_only` (`annotation.mask_blend`: the ID image's values
  are declared ids; the class image agrees with each id's class; the
  engine counted no non-integer ids), `mask_vs_geometry`
  (`annotation.mask_offset`: the alone-pass silhouette's box centre
  within 2 % of the projected hull span of the projected hull box's
  centre, its width/height within 5 %, 1 px floor; a hull in frame with
  no pixels, or pixels with no hull, fails), `box_vs_mask`
  (`annotation.box_mismatch`: IoU 0.8 at >= 64 px, 0.5 at >= 16 px, not
  claimed below; the record's `bbox_2d_tight` is its visible pixels'
  box to a pixel), `depth_vs_geometry` (`annotation.depth_range`: no
  sky under the mask; the depth band bounded by the hull's nearest and
  farthest corners; the nearest depth no farther than the nearest
  keypoint; the record's min/median are the file's), `visibility_vs_scene`
  (`annotation.visibility`: visible pixels inside the alone footprint;
  hidden footprint pixels explained by something nearer; overlaps owned
  by the nearer object; recorded counts, fractions and occluders
  re-counted; every occluder declared), `identity_stable`
  (`annotation.identity`: one id, one integer across every frame and
  camera, the engine's `render.json` echo, and -- with `--against` --
  a second run of the same spec), `applied_intrinsics`
  (`annotation.intrinsics`: the engine's applied field of view within
  0.1 deg of 2 atan(width / 2 fx), the applied picture size and lens the
  record's). `label_files` also checks the declared `_depth.f32` and
  every declared alone pass and fails `annotation.files`;
  `drawn_airframe` fails `aircraft.placeholder_drawn`.
  `mask_containment` / `depth_range` are kept for version-5 manifests
  and report NOT RUN naming their successor on any manifest that
  declares `objects[]`. Every check is NOT RUN without a bundle and
  without `objects[]`, by sentence. The verifier imports nothing from
  `labels.py` / `objects.py`: the ID images, alone passes, `.f32` depth
  and `render.json` are read with numpy and Pillow here; the hull is
  re-based from the mesh manifest (when the cited file with the cited
  digest is on this machine) or taken from the airframe block; the
  projection is `project_point`'s pinhole; the ray-box depths are a
  slab test written here.
* **`flightsim.verify`** prints the seven beside the geometry checks,
  prints `refused by name: annotation.mask_offset (mask_vs_geometry)`
  after the report for every FAIL that has a name, and records the
  verdict atomically (a temporary in the run directory, then
  `os.replace`) -- package G's workers write verdicts in parallel while
  the campaign reads them. `ok` is false on any FAIL, so the export
  refuses the run.
* **`tests/test_annotation_gates.py`** (30 tests): a fabricated run --
  the producer's manifest 6 over synthetic telemetry (a 747, an A320
  crossing 400 m ahead, a 600 m chase station and the wingman slot),
  and a bundle painted by the test's own arithmetic: three elementary
  rotations for the camera and the airframe, a ray through every pixel
  centre, the slab test against each airframe's box, a z-buffer over
  the boxes and the ground plane; the ID image, the class image, the
  float depth, the 16-bit depth, one alone pass per aircraft and a
  `render.json` in the commandlet's shape, then `attach_engine_labels`.
  A consistency test pins the painted primary against the producer's
  `bbox_2d` to a pixel before anything is graded. The clean run passes
  every gate and `verify_run().ok`; then every brainstorm §3.6 mutation
  fails the named check: the mesh origin 3 m along the body axis
  (`mask_offset` -- named on a wingman frame, every chase frame having
  passed: a chase camera looks down the axis), two ids swapped in the
  engine's echo and in a frame's labels (`identity`), swapped in the
  pixels alone (`visibility`: the primary's id outside its own
  footprint) and in every pass (`mask_offset`), the ID image blurred
  (`mask_blend`, through the class image), an undeclared stencil value
  and an engine non-integer count (`mask_blend`), the depth scaled 1.02
  with the record re-derived (`depth_range`, the nearest-keypoint
  clause), the occluder hidden from the full pass (`visibility`, the
  overlap owned by the farther object), an object dropped where
  nothing hides it (`visibility`), an undeclared occluder, the applied
  FOV 1 deg off (`intrinsics`), a declared alone pass missing
  (`files`), a tight box the record did not measure and a silhouette
  cut to half its hull (`box_mismatch`), a silhouette shrunk to 80 %
  at the same centre (`mask_offset`, the extent clause). Also: NOT RUN
  without a bundle and on a version-5 shape; identity across two runs
  of one spec passing and failing; the CLI's exit codes, the printed
  refusal and the recorded `failure`; the atomic verdict.
* **`tests/visual/annotation_sheets.py`** (+ `draw.py`, PIL only):
  `write_sheets(run_dir, out)` writes `build/visual/<check>.png` for a
  real run or the fabricated one, each captioned with the check's
  verdict: `mask_integers_only.png` (ids colourised, offending pixels
  red), `mask_vs_geometry.png` (mask edge, projected hull wireframe, CG
  cross, hull-box centre, mask-box centre), `box_vs_mask.png` (both
  boxes, IoU stamped), `depth_vs_geometry.png` (heatmap over the
  aircraft's depth band, the nearest keypoint and its predicted depth
  beside the measured), `visibility_vs_scene.png` (each alone pass
  beside the full pass, hidden footprint pixels red),
  `identity_stable.png` (the id strip: objects x frames x cameras, and
  the engine's echo). Three tests: one writes them on the clean
  fabricated run and asserts each sheet's marks by colour count and
  its record `[PASS]`; one writes them on the 3 m origin-shifted run
  and asserts the `mask_vs_geometry` record carries `[FAIL]
  mask_vs_geometry -- annotation.mask_offset`; one makes a painter
  throw and asserts the record says `drawn: false` and the CLI exits
  1. The other five mutations (id swap, blurred ID image, depth x1.02,
  hidden occluder, FOV +1 deg) are applied and asserted by the
  verifier tests in `tests/test_annotation_gates.py`, with no sheet of
  their failing run.
* **Mutation guards** (`scripts/mutation_check.sh`, the package-D
  block): the two repaired station guards and nineteen new ones -- the
  `failure` key, the alone-pass file, the two superseded version-5
  checks, three `mask_integers_only` clauses, the extent and centre
  clauses of `mask_vs_geometry`, the IoU clause, the nearest-keypoint
  clause, three `visibility_vs_scene` clauses, the frame and echo
  clauses of `identity_stable`, the field-of-view clause, the CLI's
  printed refusal and the atomic verdict write. Every old-string is
  multi-line or otherwise unique
  in its file. Each was applied by hand with the script's own
  replacement, its test file run, the source restored byte-identical
  (`cmp` against a pristine copy), `__pycache__` purged: 21 of 21 fire (the run found two defects in the block itself first -- an assertion phrase the wrong clause also printed, and an apostrophe idiom that unbalanced the shell and silently skipped three entries -- both fixed and re-confirmed).
* **Contracts page** (§4 "as landed"): the five departures above,
  each with its measurement.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_annotation_gates.py tests/test_camera_labels.py tests/test_camera_verify_corruption.py
    .venv/bin/python tests/visual/annotation_sheets.py            # fabricates build/visual/fabricated_run and writes the six sheets
    .venv/bin/python -m flightsim.verify build/visual/fabricated_run   # every gate PASS; exit 0
    .venv/bin/python - <<'EOF'
    # the Phase 1 defect at a tenth of its size, then the verdict by name
    from tests.test_annotation_gates import fabricate_run
    fabricate_run("build/visual/shifted_run", offset_body=(3.0, 0.0, 0.0))
    EOF
    .venv/bin/python -m flightsim.verify build/visual/shifted_run     # [FAIL] mask_vs_geometry ... refused by name: annotation.mask_offset; exit 1
    .venv/bin/python tests/visual/annotation_sheets.py build/visual/shifted_run --out build/visual/shifted
    ./scripts/mutation_check.sh                                        # the package-D block: every guard 'ok'
    # A real run, once rendered on Windows with -labels:
    .venv/bin/python -m flightsim.verify runs/<id> [--against runs/<id2>]
    .venv/bin/python tests/visual/annotation_sheets.py runs/<id> --out build/visual/<id>

**Not verified here (no engine in this container).** Every number the
checks grade came from a bundle painted from boxes; no real ID pass,
alone pass or `.f32` has been read. In particular: whether a real
airframe's silhouette (not a box) lands inside the 5 % extent, 2 %
centre and 0.8 IoU tolerances against a box hull on the shipped
presets -- the first rendered chase and wingman frames measure this,
and `mask_vs_geometry.png` / `box_vs_mask.png` show it; if a correct
render fails, the tolerance moves on the contracts page, not in a
test. Whether the commandlet's alone pass and ID pass rasterise the
same silhouette to the pixel (the 3 % visibility tolerance assumes
edge pixels only). Whether the engine's `applied_fov_deg` is the
horizontal field of view the record implies (the check assumes
`Capture->FOVAngle` is horizontal, as the commandlet's own FOV formula
is). That `attach_engine_labels` on a real bundle writes
`bbox_2d_tight` to the pixel the verifier re-derives (it does on the
fabricated one). No C++ was touched by this package.

**Limitations.** The hull is a box: the converter's measured extent
when the cited mesh manifest with the cited digest is on the verifying
machine, else the airframe block's extents box (this clone: always
the latter) -- so the checks bound a silhouette by its box, and an
oblique view of a real airframe is graded against a box larger than
its silhouette. A traffic aircraft's per-frame state is not in the
manifest; its placement is the record's `bbox_3d_camera` (stated in
every detail) and only its projection, pixels and depth are graded
independently. A shift along a chase camera's line of sight is
invisible to `mask_vs_geometry` (measured: 3 m at 600 m moves the
centre 0.06 m); the second camera or `depth_vs_geometry` sees it, and
a single-camera chase run cannot be cleared of it by this check. A
depth scale under 2 % inside 200 m is inside 1 % + 2 m and not
claimed. `mask_integers_only` cannot see a blend that rounds to a
declared id when the class image blended the same way; the engine's
`non_integer_id_pixels` is the measurement there. `identity_stable`
is NOT RUN without a render (the engine's echo is half the evidence).
`drawn_airframe`'s version-3 / `origin_basis` gate (contracts §0.1) is
not landed: it changes `test_a_mesh_drawn_at_the_recorded_origin_passes`
in a file this package may only add to. `labels.py`'s
`NOT_CLAIMED_OBJECT_PX` (12) and the contract's 16 px IoU floor differ;
the verifier uses the contract's 16 and `labels.py` (not this
package's file) still says the schedule stops at 12. `tests/test_messages.py`
fails on package G's `campaign.arguments` / `campaign.state` (no
catalogue entry) and two names G still lists as future, and
`tests/test_platform.py`'s utf-8 sweep names `core/campaign/campaign.py`
and `tests/test_campaign.py` -- G's, not D's; D's names are retired
from `ALLOWED_FUTURE`, the scanner sees `failure=` and `FAIL_* =`, and
every text read in D's files states its encoding (the sweep found four
that did not, fixed before landing). Sheets are drawn from the fabricated run's
box airframes here; on a real run they show the beauty-less ID image
(no beauty frame is composited).

## P2-I/page -- the non-technical interface (package I, part 2: the guided page over the campaign)

**What was measured, and what was defective.** The page was built
against the campaign as it landed (package G) and the catalogue
(part 1), and three things were measured before a line of the page
was written. (1) A real headless case of a two-second flight costs
about a second and 1.1 MB on this machine (`Campaign.run` over
`flightsim.capture`, no engine, `--max-previews 1`), so the tests run
the REAL pipeline rather than a fake: every campaign in
`tests/test_webapp_generate.py` flies. (2) The preview's first honest
run refused: "photos of the a320 over the alps ... tower view" drew
`location: matterhorn` from the policy and the capture CLI refused
`camera.terrain_clearance` (the tower placement at -1779 m AGL under
the massif) with exit 2 -- the campaign row says only "exited 2; its
log is ..." (`core/dataset/batch.py` `case_row`), so the page would
have shown nothing but a log path. `capture_refusals()` now reads the
CLI's `REFUSED -- <name>:` and `[<name>] message (requested X, limit
Y)` lines and renders them through the catalogue with the numbers:
"The camera's path drops 1781.2 m below the minimum height above the
ground; it must stay at least 2 m above the terrain." (3)
`core/messages/catalog.yaml` had no entry for `campaign.state`,
`campaign.arguments` or `campaign.duplicate_case` when this part
landed (contracts §6.3 gave the sentences to package I;
`tests/test_messages.py` failed on that HEAD for the first two and for
two names package G left in `ALLOWED_FUTURE`). The catalogue is not
this part's file; the page showed the producer's own message for
those three with `details.catalogued: false`, and the need was stated
in contracts §8. **As landed since:** commit 0958a45 added the three
entries and `tests/test_messages.py` passed at that commit (18
passed); the page now renders those three through the catalogue like
every other name. Measured at 7b0a39a: `tests/test_webapp_generate.py`
passes (45 passed across it and `tests/test_messages.py`, one
failure), and `test_messages.py::test_every_refusal_name_in_the_code_
has_a_catalogue_entry` fails again for four names later packages
emit without an entry (`export.run_names`, `export.verification_stale`,
`export.out_directory`, `compile.unreachable`) -- the same shape of
gap, on the catalogue's file, not this part's.
Also found: `core/agent` (package H) does not exist on this branch, so
the page calls `core.campaign` directly, as the contract's §8 lists it.

**What was built.** `webapp/generate.py` (new): the campaign-facing
service layer -- `words()` is the ONE place a refusal is put into
words for the page (`{sentence, hint, details: {rule, message,
catalogued, actual?, limit?, unit?}}` from `core.messages.explain`;
the rule name never enters a default field); `compile_round()` runs
the compilers' question round exactly as `/compile` does (LLM with the
regex fallback recorded, or regex with its one camera question; at most
three questions); `paragraph()` reads the compiled spec into one
plain-language paragraph (airframe, places, conditions including the
policy's leaves in words, viewpoints, count, format, flight length);
`estimate()` states frames per case from the recorder cadence and
projects disk and time ONLY from a measured case (`basis` says which;
unmeasured is `None`); `plan_refusals()` renders the validator's
violations and the sampler's policy defects; `GenerateService.preview`
runs slot 0 through `core.campaign.workers.run_index` (the campaign's
own worker function: `--max-previews 1 --card`, plus `--render` when an
engine is present) and returns the overlay PNG when pixels were drawn
or the geometry preview otherwise, saying which, with the measured
`{frames, bytes, wall_seconds}`; `start` is `Campaign.create` +
`plan()` + `run()` in a daemon thread (one per server process);
`progress_from()` computes everything the page shows from
`ledger.jsonl` on every call -- headline in the catalogue's words
(`progress.campaign.<state>` with done/total), images so far,
per-status counts with `progress.case.*` sentences, refusals by name
rendered with their counts, `histograms()` over the rows' `sampled`
draws (numeric leaves in six bins over the realised range,
categorical by count), and the time left from the MEASURED mean
seconds per completed case; `events()` is a server-sent-event
generator over `StreamingResponse` (no `sse-starlette`): a `progress`
event now and on every change, `end` on a terminal state, `idle` when
nothing will change until a resume; `frames()` lists one picture per
camera per captured case OFF THE DIRECTORIES (overlays, else previews,
else frames -- a frame the renderer never wrote is never a broken
image); `download()` is `Campaign.export(format)` zipped with its card.
`webapp/server.py`: the §8 endpoints (`POST /generate/plan|preview|
start`, `POST /generate/{id}/pause|resume|cancel`, `GET /generate/{id}`,
`/events`, `/frames`, `/download?format=`), plus `GET /generate.html`
and the two guarded image routes; every one a thin wrapper that maps
`GenerateRefusal` to its status code; nothing above the new block
changed. `webapp/static/generate.html` (new): one page, six states
(ask, clarify, preview, generate, review, download), vanilla JS, a dark
theme, `EventSource` for progress with polling as the fallback, every
refusal shown as its sentence with the rule name under a `<details>`
disclosure, every screen's command in the fixed "expert path" footer.
`webapp/static/index.html`: one link to the new page. Seventeen tests
in `tests/test_webapp_generate.py` (`TestClient`): the question round
for an imagery prompt with no viewpoint; the answer round's paragraph
and unmeasured estimate; the LLM fallback stated; a refusal as a
catalogue sentence and never a raw name in the default fields (plan
and 409 shapes, `words()` directly, the log reader); the preview flies
one case, serves its PNG, measures it and refuses to climb out of its
directory; a refused capture in words with the log's tail; progress
from a ledger the test writes by hand (counts, histograms, refusals,
the time estimate from the measured cost, the truncated last line
dropped); no time claim before a case; a real campaign to `done` with
the event stream's `progress` and `end`; the gallery off the
directories (a deleted picture disappears); the download zip whose
`dataset.json` names the format (and the campaign's default format,
and a refused one); an empty campaign's export refused in words;
cancel/resume through the campaign's transitions. Two mutation guards
appended to `scripts/mutation_check.sh`, each applied by hand,
confirmed to make the test file fail, and the source restored
byte-identical: the catalogue-only rule (the default field made to
carry the raw rule name) and progress-from-ledger (the ledger read
replaced by nothing).

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_webapp_generate.py
    .venv/bin/uvicorn webapp.server:app --host 127.0.0.1 --port 8008
    # then open http://127.0.0.1:8008/generate.html -- try the first example prompt,
    # answer the camera question, press "Fly one sample and show me", then Generate.
    # The same flow from the terminal:
    curl -s localhost:8008/generate/plan -H 'content-type: application/json' -d \
      '{"prompt":"photos of the a320 for 2 seconds in varied weather","tier":"regex","images":20}' | head -c 600
    curl -s localhost:8008/generate/plan -H 'content-type: application/json' -d \
      '{"prompt":"fly the 747 at 500 m over 2000 m terrain, chase view","tier":"regex"}' | .venv/bin/python -m json.tool | grep -A3 sentence
    curl -s localhost:8008/generate/start -H 'content-type: application/json' -d \
      '{"prompt":"photos of the a320 for 2 seconds in varied weather","answers":[{"id":"camera_view","answer":"chase"}],"images":20,"tier":"regex"}'
    curl -s localhost:8008/generate/<id>            # progress from the ledger, in words
    curl -sN "localhost:8008/generate/<id>/events"  # server-sent events until `end`
    curl -s localhost:8008/generate/<id>/frames | head -c 400
    curl -o dataset.zip "localhost:8008/generate/<id>/download?format=yolo" && unzip -p dataset.zip yolo/dataset.json | grep '"format"'
    scripts/mutation_check.sh 2>&1 | grep "guided page"

The last line prints two `ok` rows; a `WEAK` row is a finding. (The
script's baseline requires the whole suite green; on HEAD
`tests/test_messages.py` is red for package G's uncatalogued names, so
the two guards were confirmed by hand -- the mutation applied, the
test file run, the file restored byte-identical, `__pycache__`
purged -- which is what the script does per row.)

**Not verified here.** No pixel: `ue_available()` is False on this
machine, so every preview and gallery picture in the tests is the
geometry preview and the `--render` branch of the preview (the overlay
PNG with mask and box) ran on no engine; the response's `engine` and
`drawn` say so. The LLM tier's compile-twice caveat (`Campaign.create`
compiles the prompt itself) was measured only with the regex tier,
where the digests agree by construction; with a model the start
response's `recompiled` flag and the page's notice are the only
guard. The page was exercised through its endpoints and by reading it,
not in a browser session with a running campaign. Nothing in this
part touches C++. `workers > 1` goes through the campaign's spawned
pool untested from the page (the campaign's own test covers 1 vs 2).

**Limitations.** The page is a product surface over one server
process: one running campaign at a time, a thread per campaign, no
queue; a server restart loses the thread but not the campaign (the
record and ledger are the truth, and `resume` continues it). The
paragraph's wording is one reading of the spec (the compiler's
`from` strings are quoted for the place); a policy leaf of a shape
the words do not know is rendered as "varied (<kind>)". Histograms
cover the leaves the ledger rows record as `sampled` (the policy's
draws), not the Phase 10 block's derived leaves (sun elevation, fog),
which live in the manifests -- `report.json`'s `realised` has those.
The time estimate divides the measured mean by the worker count and
assumes cases keep costing what the completed ones did. The gallery
caps at 60 pictures and shows one per camera per case; the frame
browser (`/frames.html`) remains the way to see every frame. The
event stream polls the ledger at the interval asked (1 s default);
`interval` and `limit` exist for tests and for a client that wants
fewer events. `campaign.state`, `campaign.arguments` and
`campaign.duplicate_case` rendered as the producer's message until
the catalogue carried them; it does since 0958a45 (a change to
`core/messages/catalog.yaml` and `tests/test_messages.py`, which are
not this part's files), so they now render as the catalogue's
sentence with `details.catalogued: true`. This
part appends to `scripts/mutation_check.sh` and to
`docs/PHASE2_CONTRACTS.md` §8 (the as-landed note and the catalogue
finding), as the rules require.

## P2-H/agent -- the agentic controller with stated authority: ten typed tools, a deterministic policy that denies by name, a trace beside the dataset

**What was measured, and what was defective.** Before this item
`grep -r agent core webapp flightsim` found nothing: no tool layer, no
authority code, no trace (subsystem maps; critique "Package G/H
baseline"). The campaign (G) exposed a library any caller could drive
around every check -- `Campaign.create` compiles a prompt, but nothing
stopped a caller from rewriting `campaign.json`'s spec, running a spec
the validator had refused, or looping forever. The four `authority.*`
names sat in the catalogue (I, part 1) and in `tests/test_messages.py`
`ALLOWED_FUTURE` with nothing emitting them. Now:

**What was built** (contracts §7, §7.1 as landed; brainstorm §7).

* `core/agent/tools.py`: ten typed tools -- `compile`, `validate`,
  `plan_campaign`, `sample`, `run`, `render`, `verify`, `export`,
  `inspect`, `report` -- each a thin call into what exists
  (`core.nl.compiler` / `llm_compiler`, `core.campaign`,
  `core.capture.verify.verify_run`, `core.capture.overlay.draw_overlays`,
  `core.dataset.export` through `Campaign.export`). JSON schemas are
  drawn from the signatures by a 40-line helper (`tool_schema`; no
  pydantic). `validate` mints the `validation_token` =
  `sha256(spec_digest + "validated")` (HMAC-free, as the contract
  states) only for a spec with no refusal; `run`, `render` and `export`
  require it for the campaign's digest. Every call goes through
  `Tools.call(tool, reason, **kwargs)`: the policy check, the tool, the
  trace line; a denial or a library refusal comes back as
  `{"refused": name, "sentence", "hint", "message", "detail"}` -- by
  name, never a stack trace, never silent; a programming error is
  raised, not dressed as a refusal.
* `core/agent/policy.py`: the four rules as one deterministic function
  with no model. `authority.stated_field` compares PROVENANCE, flattened
  (`flatten`, `stated_moves`): a user / inferred / sampled field moved
  or dropped; a field newly claiming one of those sources ("stated on
  the person's behalf"); a system-chosen field changed without a
  recorded edit (source `derived`/`model` with a `from`). Checked on
  every tool input that carries a spec, and on the case spec AFTER a
  per-slot run (sampled leaves allowed as new). `authority.
  validation_token` recomputes the token itself (`expected_token`) --
  the thing that mints is not the thing that checks. `authority.
  refusal_is_not_a_run` remembers every refusal a digest was seen with
  and denies `run` before the token is even looked at, quoting the
  refusal's own sentence. `authority.budget`: calls (denied ones
  count), re-samples of one slot, wall time (injectable clock). Each
  denial is a `Denial(constraint=..., message=...)` the catalogue
  renders.
* `core/agent/trace.py`: `trace.jsonl` beside the campaign, one line
  per call `{t, tool, input, output, reason, policy}`, spec inputs as
  their digest, append-only and flushed per line; the controller's own
  decisions are lines whose tool is `controller`.
* `core/agent/controller.py`: `Controller(tools).run(Request(prompt,
  images, words, format, seed, answers, render, policy))`: compile ->
  validate (token) -> plan_campaign -> sample a preview -> run each
  previewed slot, verify it read-only, ask render whether pixels exist
  -> run the campaign to its target through its own exit criterion ->
  report (count against the request, coverage of the requested bins,
  no captured-but-unverified case in the yield) -> export. On a refused
  slot it says in one sentence that the sampler re-draws only
  system-chosen leaves and draws the next slot, up to the re-sample
  budget, then escalates `campaign.target_unreachable` in catalogue
  words. A clarifying question is escalated as a question, never
  answered for the person. Runs with no model; `Tools(tier="llm")`
  lets the configured model interpret the prompt and falls back,
  recorded.
* `flightsim/agent.py`: `python -m flightsim.agent "<prompt>" --images N
  --out DIR [--format F] [--vary WORDS] [--policy JSON] [--seed S]
  [--tier regex|llm] [--answer id=text] [--render] [--preview K]
  [--max-calls] [--max-seconds] [--max-resamples] [--json]`; exit 0
  done, 1 escalated (the sentence says why), 2 bad argument.
* `docs/COMMANDS.md`, generated by `scripts/agent_commands.py` from the
  schema: every tool with its parameters, its CLI equivalent and its
  page equivalent; `--check` fails when the doc is stale and the test
  runs it.
* `core/agent/mcp_server.py` (optional): serves the same `Tools.call`
  over MCP when `mcp` is installed; it is not, and must not become,
  required -- without it `serve()` prints a sentence and exits 2.
* `tests/test_agent.py` (11 tests, ~18 s): the schemas and the doc;
  the token minted only by `validate` and recomputed in the test; a
  scripted rogue that (a) moves a user field, promotes a default to
  `user`, nudges a default without an edit, and adds policy words over
  a stated policy -- five `authority.stated_field` denials, each in the
  trace with the rogue's reason; (b) runs, renders and exports with no
  token, a junk token and a foreign token -- six `authority.
  validation_token` denials and nothing ran; (c) plans the unflyable
  747 and runs it on a FORGED token -- `authority.refusal_is_not_a_run`
  with the stall-margin sentence, ledger absent; (d) exceeds the call
  budget, the wall budget on a fake clock and the per-slot re-sample
  budget -- `authority.budget`; a cooperative agent completing a
  90-image campaign in two headless cases with every trace line one
  sentence and no denial, the stated fields of every case byte-equal to
  the compiled spec's; the controller escalating in the catalogue's
  words and running nothing; the re-sample loop on an infeasible policy
  (three refused slots, only the policy's leaf drawn, the person's
  280 kt untouched, `campaign.target_unreachable`); the CLI's three
  exit codes.
* Six mutation guards in `scripts/mutation_check.sh`, one per rule
  plus the token's minting condition and the trace write; each applied
  by hand, the test file run, the file restored byte-identical and the
  caches purged: 6 of 6 fire.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:warnings tests/test_agent.py
    .venv/bin/python -m flightsim.agent "fly the a320 at 3000 m for 5 seconds in varied weather at different times of day, chase view" \
        --images 90 --out campaigns/agent-demo --preview 2
    cat campaigns/agent-demo/trace.jsonl | .venv/bin/python -c "import sys,json; [print(r['tool'].ljust(14), r['policy'], '|', r['reason']) for r in map(json.loads, sys.stdin)]"
    .venv/bin/python -m flightsim.agent "fly the 747 at 10000 ft and 40 kt for 5 seconds, chase view" --images 5 --out campaigns/agent-bad   # exit 1, catalogue sentence
    .venv/bin/python scripts/agent_commands.py --check
    ./scripts/mutation_check.sh 2>&1 | grep -A 6 "authority.stated_field"

**Not verified here.** No engine: `render` reported `drawn: false` on
every run and the export was labels-only; `inspect` never drew an
overlay (no frame file existed). The LLM tier was not exercised (no
provider is configured in this container; the regex path is the one
measured). MCP serving was not exercised (the package is not
installed; only the tool list it would advertise is checked). A
runtime's own pre-tool hook (the second enforcement point brainstorm
§7.2 asks for) does not exist here.

**Limitations (stated, not claimed).** The token is not a secret: it
stops an assistant from skipping validation, not a reader of this
repository -- the refusal-keyed check is what stops a forged token on
a refused spec. `compile` does not apply the web app's planner
sequence (`webapp/runs.py`); the campaign path is what runs, as in G,
and the move to core is an open item that edits I's files. A per-slot
`run` does not move the campaign's state (the controller finishes
through the campaign-id form, which does). Denied calls count against
the budget by design. `test_messages.py::test_every_refusal_name_in_
the_code_has_a_catalogue_entry` failed at the HEAD before this package
(`campaign.arguments` and `campaign.state` are emitted by G and had
no catalogue entry; I's to add) and still failed after it (as landed:
0958a45 added them and the test passed at that commit; at 7b0a39a it
fails again for four names of later packages, stated in P2-I/page
above), as did
`test_platform.py::test_no_text_io_without_utf8_encoding` (eight
text I/O calls without an encoding in `core/campaign/campaign.py`,
`tests/test_campaign.py` and `webapp/generate.py` -- G's and I's
files; every call in this package names `utf-8`; it passes at
7b0a39a, 11 passed); this package
adds no new refusal name and no offender. `Campaign` has no `create_from_spec`: when
the tool layer's spec differs from the campaign's own compile (the LLM
tier, or policy words planned on), `plan_campaign` writes the adopted
spec into `campaign.json` through the campaign's own `_save` and says
so in `tier` -- a classmethod on G's file would be cleaner.
