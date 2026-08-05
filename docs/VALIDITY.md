# What this simulation can and cannot support

Status: **Phases 0-1 complete.** This document grows with each phase. Everything
below is scoped to what has actually been built and measured; nothing here is
aspirational.

Read this before quoting any number this system produces.

---

## 1. What is currently supported

A trimmed fixed-wing transport can be initialised at a specified altitude and
calibrated airspeed in still air over flat terrain, and integrated forward at a
fixed timestep with verified initial conditions and verified propulsion state.

Measured, Gate 0, 9/9 conditions (3 airframes x 3 envelope points), assertion
run with mass held constant over >= 3 phugoid periods:

* altitude excursion **1.3-4.2 m**
* calibrated airspeed excursion **0.09-0.22 kt**
* roll excursion **0.00 deg**
* altitude oscillation **shrinking** in every case (growth -0.47 to -1.71 m),
  so the phugoid is damped rather than merely slow

Phase 1 adds the path from a sentence to that run: a prompt compiles to a
scenario spec in which every field records whether a human stated it, whether it
was inferred from a vague phrase, or whether it was defaulted; the spec is
rendered as a table, edited, validated, and only then run. Measured, Gate 1:

* the same spec runs **bit-identically** twice (equal SHA-256 over all recorded
  telemetry)
* the digest is content-addressed -- two different sentences commanding the same
  simulation hash the same, and any changed value changes the digest
* impossible requests are rejected by **name**: `altitude.terrain_clearance`,
  `airspeed.stall_margin`, `envelope.trim_feasible`

Steady wind is applied and is verifiable in the output (crab angle moves 0.00 to
6.44 degrees under a 25 kt crosswind and returns when it is removed).

That is the whole of it. There is no control law, no turbulence, no terrain
model, and no rendering.

---

## 2. What is NOT supported, and must not be claimed

### 2.1 No aircraft here has validated fidelity

Every stock JSBSim model carries the same disclaimer, quoted rather than
paraphrased:

> This model was created using publicly available data, publicly available
> technical reports, textbooks, and guesses. [...] If this model has been
> validated at all, it would be only to the extent that it seems to "fly right"
> [...] this model is meant for educational and entertainment purposes only.

This applies to **all three** airframes in use. Specifically:

| Model | Release | Data pedigree | Licence declared |
|---|---|---|---|
| `global5000` | ALPHA | Cites AIAA 2016-3525 (Moellemi, Jafer, Towhidnejad) | **none** |
| `737` | BETA | Aeromatic + "guesses" | GPL |
| `B747` | ALPHA | author "Unknown" | GPL |

`global5000` is the only one with a traceable published source, and it is also
the only one declaring no licence at all. **No claim of a validated transport
model is supportable with stock data.** Any agreement with published performance
figures is a coincidence until Phase 7 measures it.

### 2.2 The trimmable envelope is a property of the tables, not the aircraft

Measured high-Mach trim boundaries at 10 km: `global5000` fails above M0.68,
`737` above M0.79, `B747` reaches M0.835. These are where the interpolation
tables give out. They are **not** the real aircraft's Mmo, and must not be
reported as performance limits.

### 2.3 A mass-held run is not a realistic run

Gate 0 asserts on a run with fuel state frozen, because a fuel-burning aircraft
has no equilibrium — mass falls ~1% per 400 s at cruise thrust and the aircraft
climbs at fixed controls. Measured, 737 at 3000 m / 250 kt over 400 s:
**+89.6 m burning fuel, +2.00 m with mass held.**

Holding mass isolates trim quality from a known time-varying parameter. It is
recorded in `FlightDynamics.provenance()["mass_held_constant"]` so a mass-held
result can never be reported as a realistic one. **Both numbers are published
for every Gate 0 condition.**

### 2.4 Derived speeds describe the model, not the aircraft

Vs, Vref and Vr are measured from each model's own lift curve rather than taken
from a table (`core/scenario/envelope.py`), because the question validation asks
is whether *the thing being simulated* can fly the scenario. Measured clean
CLmax: B747 1.192, 737 1.182, global5000 0.998.

The B747's resulting Vs of 155 kt at 250 t falls inside the published clean 1 g
band of roughly 150-165 kt. **That agreement is a sanity check, not a
validation.** It is one point, on one airframe, against a figure quoted from
memory rather than from a controlled reference document, and §2.1 still applies.
Vref uses 1.30 x Vs by operational convention and Vr 1.10 x Vs as an envelope
bound; neither is a performance calculation.

### 2.5 A rule-based parser is not language understanding

The NL compiler is regular expressions over a fixed vocabulary. It is
deterministic, which is the property the reproducibility claim needs, and it is
narrow. It will misread sentence shapes it has not seen. Two consequences:

* Anything it does not recognise is reported in `spec.notes` rather than
  dropped, and cinematic terms are explicitly listed as ignored.
* The rendered table exists so a human checks the interpretation **before** the
  run. A spec is not evidence that the prompt was understood; it is evidence of
  what will be simulated.

### 2.6 Not yet built

No control laws (Phase 2), so nothing yet commands altitude or airspeed and the
closure assertion of §2.8 does not exist. No turbulence or orographic coupling
(Phase 3) -- a spec requesting turbulence is refused rather than run in smooth
air. No terrain model (Phase 4), no Unreal integration (Phase 5), no rendering
(Phase 6), no validation against published reference data and no credibility
scorecard (Phase 7).

Nothing in this repository currently supports a claim about aircraft response to
environmental conditions.

### 2.5 No EO/IR sensor fidelity exists

None has been built. Unreal has no native EO/IR simulation and no MISB/KLV
support. A post-process "thermal look" would be visually plausible and **not
radiometrically calibrated**. Nothing here is traceable as sensor imagery.

---

## 3. Reproducibility: two different claims, kept separate

**Physics** is intended to be bit-reproducible from a spec, and that is a
strict claim which Phase 1 must demonstrate. Contributing factors already in
place: fixed timestep set at construction and never varied; step counts derived
from the fixed rate rather than accumulated from wall time; no RNG anywhere in
the core; aircraft XML fingerprinted by SHA-256.

**Rendering** will not be bit-deterministic. Movie Render Queue is not
bit-deterministic and Epic documents no fix. When Phase 6 exists it will be
described as reproducible-within-tolerance, never as bit-identical.

Not yet done: floating-point flags on the physics core are unaudited
(`-ffast-math` must be off), and no run manifest is emitted yet (Phase 7).

---

## 4. Known correctness hazards in the underlying library

Four measured JSBSim behaviours produce silently wrong runs. All four are
guarded here, with regression tests that have been mutation-checked — each
guard was disabled in turn to confirm the corresponding test actually fails.
Full detail and measurements in [JSBSIM_CORRECTIONS.md](JSBSIM_CORRECTIONS.md):

1. Writing an unknown property **succeeds silently** and does nothing.
2. `ic/vc-kts` is silently overwritten by `ic/lat-geod-deg` — a requested
   300 kt CAS at 10 km became Mach 1.28.
3. `ic/vw-*-fps` NED wind components are read-only despite being documented as
   settable ICs; writes are ignored without diagnostic.
4. Aircraft load with engines stopped, and thrust cannot distinguish a running
   engine from a stopped one at zero throttle.

Two §6.2 items remain **unverified** and must be confirmed before Phase 3
depends on them: the turbulence type enum (`ttMilspec=3` etc., not exported to
Python) and the probability-of-exceedence 0-7 severity mapping
(`SetProbabilityOfExceedence` not exposed).

---

## 5. Licensing flags

* **JSBSim engine**: LGPL 2.1. Dynamic linking keeps closed-source code
  unaffected.
* **Aircraft XML is licensed separately and inconsistently.** `f16.xml` declares
  GPL; `f15.xml` declares nothing at all. `global5000.xml`, currently the best
  data pedigree in use, declares no licence. Engine LGPL does **not** cover
  these.
* **Cesium ion** (Phase 4+): the free Community tier excludes organisations with
  >$50K revenue, >$50K funding, or government/funded research work. Commercial
  is $149-524/mo. This is a real cost and applies to funded research.
* **DTED Levels 1 and 2** are presumptively restricted distribution. The
  pipeline will target SRTM, Copernicus DEM GLO-30, and USGS 3DEP.
