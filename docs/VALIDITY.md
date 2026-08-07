# What this simulation can and cannot support

Status: **Phases 0-7: every gate passes.** Phase 6's gate passes on its four
measurable clauses with a placeholder airframe and a default terrain material —
the section below is precise about what that does and does not establish. This
document grows with each phase. Everything below is scoped to what has actually
been built and measured; nothing here is aspirational.

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

**Phase 5: the two hosts have now been compared, and they agree.** The build
constraint that blocked this is a compiler-version check and nothing more —
UE 5.5 accepts Xcode 15.2–16.9, macOS 26 ships Xcode 26, and a second Xcode
installed alongside it and selected per process through `DEVELOPER_DIR` is
enough. No `sudo`, no `xcode-select`, and the machine's default toolchain is
untouched. macOS 26 also refuses to *launch* Xcode 16.4's GUI, which is
irrelevant: UE invokes `clang` and `xcodebuild`, and those run.

What was established before any of that, and is still what makes the comparison
meaningful:

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
* The **aircraft and engine data are byte-identical** between the two hosts.
  `B747.xml`, `GE-CF6-80C2-B1F.xml` and `direct.xml` hash the same in the
  jsbsim wheel and in the plugin's staged `Resources/JSBSim`. Same engine, same
  model, same numbers: a divergence could only be the integration path.

`FlightSimScenarioCommandlet` drives a scenario through the Unreal host with no
editor and no window — it builds a world, pins the georeferencing origin at the
spec's ground point, spawns a query-only ground slab so JSBSim's ground callback
has something to hit, places the aircraft by its centre of gravity at the spec's
initial conditions, and steps at a fixed 1/120 s. Measured, Gate 5 (B747, 3000 m,
250 kt CAS, 60 s, hands off from trim in both hosts, mass held):

| channel | max difference | stated tolerance |
|---|---|---|
| altitude | 3.6 × 10⁻⁴ m | 5 m |
| true airspeed | 4.2 × 10⁻⁵ kt | 2 kt |
| roll | 2.1 × 10⁻⁸ ° | 1° |
| pitch | 1.1 × 10⁻⁵ ° | 1° |
| heading | 7.9 × 10⁻⁸ ° | 1° |
| load factor | 2.2 × 10⁻⁷ | 0.05 |

The two hosts also trim to the same solution independently: throttle 0.579150 in
Unreal against 0.579149769 headless, pitch trim −0.276739 against −0.27673930.

Three things about this result are worth stating plainly.

* **The tolerances were not tight.** Agreement is four orders of magnitude
  inside them. That is the expected outcome when both hosts step the same
  library at the same rate from the same trim, and it means the tolerances would
  not have caught a small integration error. What they would catch — a substep
  accumulator dropping frames, an ECEF round trip losing precision — is absent
  at the 10⁻⁴ level, which is a stronger statement than the tolerance asks for.
* **The comparison is on the recorded clock, not the sample index.** The two
  recorders have the same nominal 0.1 s period and do not sample at the same
  times: the headless one comes out at ~0.1075 s and the Unreal one at 0.1 s
  exactly, a 7% stretch that reaches four seconds of skew over a 60 s run.
  Comparing by index would have compared 60 s of one host against 56 s of the
  other. On this nearly flat cruise that would have cost tolerance rather than
  failing outright; on a climbing scenario it would have failed a correct host.
* **Both hosts fly open loop.** The headless host can hold a commanded state
  with TECS; the Unreal host has no autopilot. The parity spec therefore sets
  `hold_state` false, so the comparison is of two uncontrolled aircraft. That is
  also the sharper test — there is no feedback loop pulling the hosts back
  together.

### The two on-screen clauses

§5 Phase 5 has three clauses and the other two are about what a viewer sees:
"control surfaces visibly articulate" and "commanded roll is visible on screen".
No number in a telemetry file can answer either.

`FlightSimRenderCommandlet` flies the same spec plus a scripted roll doublet
with the renderer up — Metal, offscreen, no window — and writes PNG frames.
`experiments/gate5_ue_parity.py --unreal-render` reads those PNGs back and
measures them. It does not read what the engine said about them: a run that
wrote the right numbers into its manifest and the wrong pixels into its frames
has to fail, and only an independent read of the frames can make it.

Measured over 110 frames at 5 Hz, 960×540:

| clause | measurement |
|---|---|
| frames show the aircraft | aircraft covers 2.77–3.79% of every frame |
| camera never inherits roll | max \|camera roll\| **0.000000°** |
| control surfaces articulate | 4 bound to geometry, 4 moved: ailerons 10.03° of travel each, elevator 5.55°, rudder 1.07° |
| commanded roll is visible | apparent bank **in the pixels** tracks FDM roll at **r = 0.99923**, over −1.9…+17.0° against the FDM's −2.2…+16.8° |

That last row is the direct regression for §1.5, which is worth restating
because of how quietly it passes every other kind of check: the previous build's
chase camera was rigidly parented to the aircraft, so a real roll of +7° to −7°
happened and was **invisible**. Every telemetry number in that clip was correct.
The test therefore cannot be "the camera was configured with the right preset" —
it has to be a measurement of the pixels, and it has to fail when the pixels do
not move. `tests/test_on_screen.py` demonstrates it failing on a render where
the FDM rolls and the image does not, and on one where the image rotates the
opposite way.

The surface deflections are read off the scene components' transforms — the
poses the renderer drew — rather than recomputed from the JSBSim properties. The
distinction is the whole point: `UFlightSimSurfaceAnimator` originally computed
deflections and rotated nothing, which is §1.5's "no control surface moved
anywhere in the clip" reproduced exactly, and a check that recomputed the
property would have passed it.

What is **not** established, and must not be claimed:

* **The rendered aircraft is a placeholder built from boxes.** It is not a
  visual asset and nothing here is a claim about visual realism, which is
  Phase 6. What the frames establish is that a JSBSim surface position moves
  geometry a viewer would see, and that attitude is legible in frame. They
  establish nothing about whether any of it looks like a 747.
* The rendered scenario is **not** the parity scenario. It carries a scripted
  aileron doublet, because this host has no autopilot and a commanded roll has
  to be commanded by something. The telemetry commandlet refuses a card with
  control inputs for that reason, so the two can never be confused.
### Breadth: the same comparison across the envelope, and in wind

Gate 5's verdict rests on one scenario. `experiments/host_parity_matrix.py` runs
the same comparison over three airframes at four envelope points — Gate 0's
three points plus one — and, for every airframe, two steady-wind cases: a 25 kt
pure crosswind and a 15 kt quartering headwind. Every case is held to the
tolerances Gate 5 declared, plus two channels added with the wind work: ground
track (latitude and longitude, 1e-4 degrees ≈ 11 m). Position is what closes
the loop on wind acting in *both* hosts — a uniform wind changes no air-relative
quantity, so a host silently flying the wind case in still air matches every
attitude channel and misses the other's ground track by hundreds of metres
inside a minute. The matrix is **not** a gate and does not change Gate 5's
verdict; it is the evidence that Gate 5's single-case result was not a
single-case coincidence.

| | |
|---|---|
| ran in both hosts | **16 of 18** |
| agree within the Gate 5 tolerances | **16 of 16** |
| worst channel anywhere | latitude, at **16%** of its tolerance — a constant 1.24 m north phase equal to exactly one 1/120 s step of position (the headless host integrates one extra step during engine start) |
| still-air channels | 1e-8 – 1e-4 of tolerance, as before |
| wind-case attitude channels | within 0.08° roll, 0.008 kt TAS, 0.03° heading |

How wind is driven in the Unreal host, and two things learned doing it:

* The plugin's own wind initial condition is **not used**: measured, its
  `SetWindMagKtsIC` re-derives the velocity state and a commanded 250 kt CAS
  comes out of RunIC at 206 kt — the same family of silent IC interaction the
  headless host's `_IC_PRIORITY` ordering exists to defeat. Instead the
  commandlet reproduces the headless sequence: calm RunIC, wind written
  directly to the FGWinds properties, a full re-trim in the wind through
  JSBSim's own `simulation/do_simple_trim`, then the same NED wind properties
  re-written every step — the same floating-point values, from the same
  conversion chain.
* The comparison starts at each host's **second** sample. The first sample is
  the trim snapshot, which the headless recorder takes before its environment
  loop has applied wind — measured, 288 kt TAS against 301 kt one sample later
  in a 13 kt headwind. Grading that instant grades the switch-on artifact
  (§1.1's initialisation-transient mistake in miniature). Exactly one sample
  is exempt per host, mutation-checked from both directions: a divergence
  living only in samples 2–4 still fails, and a comparison that skipped five
  samples fails the guard.
* Heading is compared **on the circle**. A crosswind case's heading wanders
  across north within seconds, and a number-line comparison of two identical
  headings straddling 0/360 reports up to 360 degrees of divergence that never
  happened. Both series are unwrapped before interpolation and differenced
  with wrapping; the still-air scenarios never crossed the seam, which is the
  only reason the original comparison got away without this.

The two that never ran are `737` and `B747` at 10000 m / 240 kt, both refused by
the spec validator's stall-margin constraint (the B747 by 34 kt). That refusal
is correct — Gate 0 reaches those points by building an FDM directly and never
sees the validator — and it is reported by name rather than dropped. The fourth
point, 8000 m / 280 kt, exists because without it the top of the envelope would
have been covered by one airframe out of three while the matrix still said "all
conditions agree". Wind directions are whole degrees by construction: the
commandlet refuses fractions because the plugin's wind IC field is an int32 and
a fractional direction would trim one wind and fly another.

### A third upstream plugin bug, found by the achieved-condition check

`UJSBSimMovementComponent::GetAGLevel` builds the downward ray for JSBSim's
ground query with its start point in **centimetres** and its end point in
**metres**, three lines apart in the same function. The intended reach is the
aircraft's altitude plus 5% of the ellipsoid radius — about 319 km — and what is
actually cast is 319 km of *centimetres*, so the ray is **3.19 km** long.

Above roughly 3.2 km AGL the trace therefore hits nothing, `GetAGLevel` returns
its miss value of 0.0, and JSBSim is told the aircraft is exactly on the deck.
Nothing reports an error. The gear and ground-reaction model simply run against
a fiction, at cruise altitude — which is every altitude that matters.

It was found because the commandlet checks the trimmed aircraft against the
condition that was commanded, including its height above terrain, rather than
assuming the placement worked: the 3000 m case answered correctly (the 3.19 km
ray still reached) and the 6000 m case reported height above terrain 0.0 m. It
is patched, recorded in `VENDORED.json` alongside the other two, re-applied by
`scripts/vendor_ue_plugin.sh`, and asserted by `scripts/check_bridge_api.sh` so
a re-vendor cannot silently drop it.

What is **not** established, and must not be claimed:

* Every case in the matrix is **flat terrain, 60 seconds, hands off from
  trim**; wind cases are steady and uniform. It says nothing about agreement
  under turbulence, wind shear, terrain, manoeuvring, or over longer runs. The
  commandlets **refuse** turbulence and a held state rather than approximating
  them, so those cases cannot be silently mistaken for tested. Steady wind is
  the only environmental condition both hosts implement.
* Agreement between the hosts is agreement about the **integration**, not about
  reality. Both hosts run the same alpha-release B747 model, whose own header
  says it "may not even properly load, and probably will not fly as expected."
  Two hosts agreeing on an unvalidated model is exactly as unvalidated as one.

Phase 7 adds the research machinery: resumable parameter sweeps, per-subsystem
seed derivation, provenance manifests, variance attribution, a validation report
and a NASA-STD-7009A credibility scorecard. Measured, Gate 7:

* an 18-case factorial sweep completes; killed at case 7 and resumed, it
  produces a **case-for-case identical dataset**
* the run **reproduces bit-identically** from its manifest across all 18 cases
* wind speed explains **99.4%** of mean-airspeed variance and 93.0% of altitude
  excursion (η²), with dispersion reported at every level
* the validation report is **mostly inconclusive**, which is the honest result

The V&V document set is at [vva/](vva/): plan, report, accreditation statement.

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

### 2.11 Validation is mostly inconclusive, and that is the finding

Of six validation targets, one is validated at u_val (B747 stall speed, against
a specification figure with deliberately wide u_D), one is validated
(turbulence σ_w reproduces MIL-F-8785C's low-altitude relation), two are
**inconclusive for want of any referent**, one was **not attempted** (modal
damping needs linearisation this build does not do), and one is not applicable.

A validation suite that returned PASS on this evidence base would be comparing
the model to itself. See [vva/VV_REPORT.md](vva/VV_REPORT.md).

### 2.12 The credibility scorecard is mostly below its own threshold

Published at `runs/gate7/scorecard.txt` against a threshold of **2**, declared
before scoring. Many factors score 0–1, and `sensors` scores 0 across the board
because no EO/IR modelling exists. That is the expected state and it is
published rather than withheld — a scorecard exists to say where the model is
weak.

Rendering is scored at 0. Frames now exist -- Gate 5's on-screen clauses are
measured on them -- but they show a placeholder box airframe, and a scorecard
factor for visual fidelity would be scoring a stand-in.

### 2.13 Not yet built

**Phase 6: Gate 6 passes, measured from the pixels.** The criteria were
recovered verbatim from the originating brief and recorded with provenance in
[BRIEF_PHASE6.md](BRIEF_PHASE6.md); the scene follows its §6.6 settings (real
Earth atmosphere values, multiscattering, both documented SkyAtmosphere
gotchas, height fog with max opacity below 1, manual exposure). Measured by
`experiments/gate6_visual.py`, which reads the PNGs back rather than trusting
the engine:

| clause | measurement |
|---|---|
| distant terrain shows range-based extinction | the **same raster** placed at ~10 km and ~30 km: sky-contrast 102.1 vs 27.8 (ratio 0.27, threshold 0.75) |
| peaks shadow the valley | shadows-on/off null test: **18,699 px** of the terrain band darken (threshold 10,000) |
| the aircraft has a ground shadow | aircraft-hidden null test, body pixels excluded: **1,181 px** of ground darken (threshold 300) |
| exposure does not breathe | sky band moves **4.9/255** across a 17.3° roll sweep (threshold 8) |
| — metric self-validation | the same flight rendered with auto-exposure pumps the sky **34.4/255**; every gate run must trip its own metric on this control or the pass is void |

The side-by-side against the old footage is produced
(`runs/gate6/side_by_side.png`) and the likeness judgment is explicitly the
reader's. What the measurements establish is that the four properties the
brief named as missing from the old footage are present.

What Gate 6 does **not** establish, and the Phase 6 work that remains:

* The airframe is still placeholder boxes; there is no aircraft asset.
* The terrain material is the engine default — no land-cover-driven
  materials, no foliage (both named Phase 6 items in the brief).
* MRQ with temporal sub-sampling is not used: the frames come from the
  offscreen commandlet, which MRQ does not drive. Recorded as a deviation.
* Shadows are dynamic CSM, not Virtual Shadow Maps — §6.6's own fallback,
  because VSM wants Nanite and a runtime procedural mesh is not Nanite.
* The visual terrain carries no collision and sits away from the flight
  path; the flown scenario remains the spec's flat terrain, answered by the
  invisible query slab. The mountains are honest scenery, not physics.

No EO/IR sensor modelling (§2.5 below). No validation against published
reference data beyond the two targets §2.11 records, and the credibility
scorecard is mostly below its own threshold (§2.12).

Claims about aircraft response to environmental conditions are supported only
to the extent Phases 3 and 4 measured them, and only in the headless host: the
Unreal host has been compared against it in **still air over flat terrain
only**, because the commandlet refuses wind and turbulence rather than
approximating them.

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
