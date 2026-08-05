# flightsim

A research-grade flight simulation system: defensible physics data and credible
visual output, driven by natural language through a validated, reproducible
scenario spec.

**Status: Phase 0 complete, Gate 0 passed 9/9.** See
[docs/VALIDITY.md](docs/VALIDITY.md) for what that does and does not support.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install jsbsim==1.2.4 numpy pytest
```

## Run the gate

```bash
.venv/bin/python experiments/gate0_trim_hold.py
```

## Run the tests

```bash
.venv/bin/pytest
```

## Layout

```
core/            zero Unreal dependency (§2.9)
  fdm/           JSBSim wrapper, trim, checked property I/O, read-only state
  environment/   environment providers            (Phase 3)
  control/       TECS + lateral, compiled to JSBSim XML autopilot  (Phase 2)
  scenario/      spec schema, validation, provenance   (Phase 1)
  nl/            prompt -> spec compiler. Emits a spec, never runs anything.
  telemetry/     read-only observers
  terrain/       DEM ingestion, procedural generation, heightfield query
experiments/     gates, sweeps, analysis, validation
ue/              Unreal project                    (Phase 5)
docs/            VALIDITY.md, JSBSIM_CORRECTIONS.md, vva/
tests/
```

## The four architectural guards already in place

The previous build of this project failed by reporting success while being
wrong. Phase 0 exists to make the specific mechanisms impossible:

| Guard | Prevents | Where |
|---|---|---|
| Catalog-checked property access | A misspelled property that writes successfully and does nothing | `core/fdm/properties.py` |
| Aircraft resolution + post-load verification | Running F-16 aerodynamics under an F-15 mesh | `core/fdm/aircraft.py` |
| Ordered ICs + post-condition check | Commanding 233 kt and starting at 201 kt | `core/fdm/fdm.py` |
| Trim failure is a hard error; engines verified by spool | Recording an initialisation transient, or trimming an unpowered glider | `core/fdm/trim.py`, `core/fdm/fdm.py` |

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
* **Four §6 reference items are wrong** in ways that silently produce bad runs,
  and two remain unverified. See
  [docs/JSBSIM_CORRECTIONS.md](docs/JSBSIM_CORRECTIONS.md).
