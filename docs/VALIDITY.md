# What this simulation can and cannot support

Status: **Phases 0-4 complete. Phase 5 BLOCKED on the build toolchain.** This document grows with each phase. Everything
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

Phase 2 adds closed-loop control. TECS runs inside JSBSim's XML at FDM rate,
not in Python, so it reproduces identically in either host. Measured, Gate 2
(B747, 6000 m, 280 kt CAS):

| channel | step | rise | overshoot | settling | steady-state error |
|---|---|---|---|---|---|
| altitude | +100 m | 20.5 s | 10.1% | 96.5 s (rate limited) | +0.000 m |
| airspeed | +15 kt | 11.0 s | 6.2% | 53.5 s | +0.000 kt |
| heading | +30 deg | 37.5 s | 0.0% | 102.0 s | −0.000 deg |
| bank | +30 deg | 2.8 s | 2.8% | 43.8 s | +0.040 deg |

The decoupling test — the direct regression for §1.2 — commands an altitude and
an airspeed step simultaneously. Altitude overshoot goes 10.1% to 12.8% and
airspeed overshoot *falls* from 6.1% to 1.1% while its settling stretches 53.5 s
to 70 s. Both channels still meet the criteria they met alone. That is a shared
energy budget, not two loops fighting.

The closure assertion (§2.8) is wired into the run harness and is demonstrated
failing as well as passing: a command the aircraft is given no time to reach
produces no output rather than a clean recording of a failure.

Phase 3 adds the environment tier: steady wind, a boundary-layer profile,
Dryden turbulence, discrete gusts, and orographic lift. Every one is a pure
function of position and time; wind contributions sum, because velocity fields
superpose (§2.4).

The null-test ladder (Gate 3) runs each feature on and off and diffs the
trajectories. All five show a measurable difference, so each one reaches the
equations of motion:

| feature | peak altitude diff | peak track diff | magnitude check |
|---|---:|---:|---|
| steady wind | 6.4 m | 364 m | settled crab **4.96°** vs atan(25/288) = **4.96°** predicted |
| boundary layer | 8.2 m | 192 m | 25.0 kt at 10 m → 38.0 kt at 200 m |
| turbulence | 37.5 m | 786 m | load-factor RMS 0.0061 g → 0.0774 g |
| discrete gust | 8.1 m | 3.7 m | Nz peaks at t=10.8 s, gust peaks at t=10.9 s |
| orographic lift | 14.4 m | 7.0 m | w reverses ±5.40 m/s across the crest |

Timestep convergence: peak altitude difference 0.098 m between 1/60 and 1/120,
and 0.048 m between 1/120 and 1/240 — halving as the step refines, which is what
justifies 120 Hz as the integration rate.

**A null test proves connection, not correctness.** It is a deliberately low bar
and it is the bar the previous build failed. Whether these models are *right* is
Phase 7's question.

Phase 4 adds terrain. Real DEMs and synthesised terrain are baked into the
**same** 16-bit raster format, with the same georeferencing conventions, and
reach the FDM through the same query — so terrain statistics are a controllable
independent variable rather than a change of code path (§3.2). Measured, Gate 4:

* ingested DEM elevations match the source to **8.6 m mean / 17.8 m max** against
  a tolerance of 80 m derived from the surface's own local curvature at the
  60 m resample
* Landscape round trip returns **0.008 m max error** and preserves relief to
  **0.000 m** and aspect ratio to 1 part in 10⁹
* synthesised slope distribution is prescribable: RMS-slope targets of 10/20/30°
  give medians of 8.9/17.5/26.4° with p99 below 45°
* orographic lift now runs over the baked raster for both terrain kinds

Cesium is *not* queried for physics. Its height query is asynchronous and its
answer depends on which LOD happens to be streamed in; a ground callback needs a
deterministic answer every tick.

**Phase 5 is blocked and Gate 5 has not run.** The Unreal host cannot be
compiled on this machine: UnrealBuildTool refuses to register Mac as a buildable
platform because the installed Xcode (26.6) is outside the range UE 5.5 accepts
(15.2–16.9). This is a compiler-version check — not a macOS limitation, and not
a plugin limitation.

What *was* established, and is real:

* The official Epic JSBSim plugin **does support macOS**. Its own
  `JSBSim.Build.cs` lists `UnrealTargetPlatform.Mac` and routes it through
  `SetupUnixPlatform()`. §3.1's MSVC/`.sln` instructions are the documented
  path, not the only one.
* A universal **arm64 + x86_64 `libJSBSim.dylib` was built** from JSBSim v1.2.4
  — the same version the headless core runs, so §2.9's "identical physics in
  either host" is testable rather than aspirational. The upstream repository
  ships no prebuilt library for any platform; the Windows instructions build one
  and `scripts/vendor_ue_plugin.sh` builds the Unix equivalent.
* The plugin is vendored reproducibly with commit, version and library hash
  recorded in `VENDORED.json`.

What is **not** established, and must not be claimed:

* **None of the bridge C++ has ever been compiled.** The camera director,
  surface animator and telemetry recorder are written against the plugin's API
  as read from its headers, and are unverified. Treat them as a design, not as
  working code.
* No trajectory has been produced by the Unreal host, so nothing is known about
  whether the two hosts agree. Gate 5 reports **BLOCKED** with its own exit
  code, distinct from pass and fail, and refuses to report a pass on the
  headless half alone.

That is the whole of it. There is no rendering.

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

### 2.6 Control gains are tuned for one airframe at one condition

Every gain in `core/control/systems/tecs.xml` was measured by sweep on the
**B747 at 6000 m / 280 kt CAS**. They are not scheduled with altitude, speed or
mass, and they have not been checked on the 737 or global5000. A gain set that
works at one point of one envelope is not a validated controller.

No gain or phase margins have been measured. §6.5 asks for ≥6 dB and ≥45°;
that requires linearisation which this build does not do, so the margin
criteria are **unverified**, not met.

### 2.7 Settling criteria deviate from §6.5, deliberately

§6.5 asks for altitude settling in 3–5·τ, which at τ = 5 s is 15–25 s. That is
not achievable for a 250-tonne transport holding a ±2 m band, and the limit is
not the controller: sweeping the pitch inner-loop gains over twelve
combinations moved altitude settling by less than a second, leaving it at 96 s
throughout. What governs it is the phugoid, period ≈87 s here.

Settling criteria are therefore referenced to 1.5× the measured phugoid period,
the same way Gate 0's hands-off window is. This is a documented deviation, not
a met criterion.

### 2.8 The orographic model is the weakest thing in the repository

Ridge lift is the linearised lower boundary condition w = U·∇h (Smith 1979).
It assumes small slopes, steady neutral flow and no separation, so above a
slope of 0.35 the result is **saturated rather than believed**.

Lee sink and rotor are worse. Separation is assumed wherever a crest is
upstream, with no dependence on lee-slope angle, Froude number or inversion
strength — all of which control whether a real rotor forms at all. The
1.3× gain and the 4-crest-height decay are documented middle choices from
FAA AC 00-57 and Doyle & Durran 2002, **not measured values**.

It also currently runs against an analytic sinusoidal ridge. Until Phase 4
couples it to a real DEM, "ridge lift over this ridge" is a precise number
about nothing.

### 2.9 Turbulence intensity words are a mapping, not a measurement

"Moderate" resolves to a target σ_w of 6 ft/s, and the POE index whose
*measured* σ_w is nearest is selected. Both the target and the achieved value
are published in the vocabulary report and the run manifest. The conventional
intensity bands themselves are an operational convention, not a standard with
a single defensible number.

Turbulence is deliberately **not active during trim** — a stochastic
disturbance makes the trim solver chase noise.

### 2.10 Terrain caveats

**The ingested DEM is cropped, not extended.** Reprojecting a lat/lon rectangle
into a metric CRS leaves empty corners. Filling them extends the nearest real
elevation outward and leaves a cliff along the seam — measured on the Gate 4
fixture, 10,781 pixels (7% of the raster) producing slopes to 84.9° where p99 of
the real data is 23.3°. The raster is therefore cropped to the largest
all-valid rectangle, so **the baked area is smaller than the source DEM**.

**Genuine interior voids are still filled** by neighbour interpolation and the
count is recorded. Filled pixels are interpolation, not measurement.

**Synthesised terrain is not a model of anywhere.** It has prescribed
statistics — Hurst exponent, RMS slope, autocorrelation length — and erosion
that produces drainage networks. That makes it a controlled experimental
surface, not a replica of any real landscape, and results over it describe
response to *terrain statistics*, not to a place.

**The erosion is qualitative.** Stream-power incision with m/n = 0.5 produces
plausible drainage, but no attempt has been made to match measured erosion
rates, and the iteration count and strength are chosen for appearance and
runtime rather than calibrated.

**Elevations quantise to 16 bits.** A raster spanning 1000 m of relief resolves
about 1.5 cm. Reported as `quantisation_m` and used to derive round-trip
tolerances rather than assumed negligible.

### 2.11 Not yet built

No verified Unreal integration (see above), no rendering
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
