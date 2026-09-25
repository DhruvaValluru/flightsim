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
