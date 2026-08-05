# flightsim

A research-grade flight simulation system: defensible physics data and credible
visual output, driven by natural language through a validated, reproducible
scenario spec.

**Status: Phases 0-1 complete. Gate 0 passed 9/9, Gate 1 passed 4/4.** See
[docs/VALIDITY.md](docs/VALIDITY.md) for what that does and does not support.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install jsbsim==1.2.4 numpy pytest pyyaml rasterio pyproj
```

`rasterio` ships GDAL in its wheel, so no separate GDAL build is needed.

## Run the gates

```bash
.venv/bin/python experiments/gate0_trim_hold.py
```

```bash
.venv/bin/python experiments/gate1_spec.py
```

```bash
.venv/bin/python experiments/gate2_control.py
```

```bash
.venv/bin/python experiments/gate3_null_tests.py
```

```bash
.venv/bin/python experiments/gate4_terrain.py
```

```bash
.venv/bin/python experiments/gate7_sweep.py
```

Gate 5 needs the Unreal host. Check whether this machine can build it:

```bash
./scripts/ue_preflight.sh
```

## Run the tests

```bash
.venv/bin/pytest
```

Every guard has a regression test, and the tests are checked against removal of
the guard they cover:

```bash
./scripts/mutation_check.sh
```

## Layout

```
core/            zero Unreal dependency (§2.9)
  fdm/           JSBSim wrapper, trim, checked property I/O, read-only state
  environment/   wind, boundary layer, turbulence, gusts, orographic lift
  control/       TECS as a JSBSim XML system, run at FDM rate
  scenario/      spec schema, validation, provenance, run harness
  nl/            prompt -> spec compiler. Emits a spec, never runs anything.
  telemetry/     read-only observers
  terrain/       DEM ingestion, spectral synthesis, heightfield query, Landscape export
experiments/     gates, sweeps, analysis, validation
docs/vva/        V&V plan, report, accreditation statement
ue/              Unreal project                    (Phase 5)
docs/            VALIDITY.md, JSBSIM_CORRECTIONS.md, vva/
tests/
```

## The architectural guards already in place

The previous build of this project failed by reporting success while being
wrong. These exist to make the specific mechanisms impossible:

| Guard | Prevents | Where |
|---|---|---|
| Catalog-checked property access | A misspelled property that writes successfully and does nothing | `core/fdm/properties.py` |
| Aircraft resolution + post-load verification | Running F-16 aerodynamics under an F-15 mesh | `core/fdm/aircraft.py` |
| Ordered ICs + post-condition check | Commanding 233 kt and starting at 201 kt | `core/fdm/fdm.py` |
| Trim failure is a hard error; engines verified by spool | Recording an initialisation transient, or trimming an unpowered glider | `core/fdm/trim.py`, `core/fdm/fdm.py` |
| Validation before execution, constraints named | Rendering a plausible video of a scenario that cannot be flown | `core/scenario/validate.py` |
| Unimplemented conditions are fatal | A spec that asks for turbulence running in smooth air | `core/scenario/runner.py` |

Every guard has a regression test, and every test has been **mutation-checked**:
the guard was disabled in turn to confirm the test actually fails. A suite that
passes while the system is broken is the failure of §1.7, and a green run is not
by itself evidence.

## Documented deviations from the brief

* **Gate 0 asserts on a mass-held run**, not the literal fuel-burning one, and
  publishes both numbers. A fuel-burning aircraft has no equilibrium; asserting
  on it would mean a tolerance loose enough to hide a real trim defect.
  Rationale and measurements in [docs/VALIDITY.md](docs/VALIDITY.md) §2.3.
* **The divergence window is 3 phugoid periods, not 60 s.** 60 s is shorter than
  one phugoid period at these speeds, so a "growing oscillation" test over it
  measures the first quarter-cycle rising rather than divergence. The literal
  60 s figures are still reported.
* **Six §6 reference items are wrong** in ways that silently produce bad runs,
  and two remain unverified. See
  [docs/JSBSIM_CORRECTIONS.md](docs/JSBSIM_CORRECTIONS.md).

## Environment hazard

macOS system Python caches bytecode **outside the repo**, at
`~/Library/Caches/com.apple.python/<abs-path>`, so `find . -name __pycache__`
purges nothing. A restored source file was once shadowed here by bytecode
compiled from a mutated version, making a correct fix look broken.
`scripts/mutation_check.sh` purges both locations; be aware of it when a change
appears to have no effect.
