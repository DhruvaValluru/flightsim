# Flight-dynamics research ledger

A running record of what was investigated, what the repository does, what
the literature and mature systems do, and what the difference means for the
aircraft in the air. Written cycle by cycle, not reconstructed afterwards.
Every measurement below was made by running this repository's own physics
headlessly (JSBSim through `core.fdm.FlightDynamics`, TECS through
`core.control.autopilot`); scripts live in the session scratchpad and are
reproduced in `flight-dynamics-audit.md`.

Commit audited: `e73aee8` (master).

---

## Cycle 1 — the flying loop, turning, climbing, timestep

### 1.1 Aircraft turn dynamics

**Current repository method.** Heading hold is a cascade inside
`core/control/systems/tecs.xml`: heading error (±180° wrapped) × `k-hdg`
(1.2) → bank demand, clipped to ±0.436 rad (25°) → bank error × `k-phi`
(3.5) → roll-rate demand → aileron PID → `fcs/aileron-cmd-norm`. The turn
itself is not computed anywhere: JSBSim rolls the aircraft, the lift vector
tilts, and the curved path follows from the equations of motion. The yaw
channel is a **washed-out yaw damper** (`ap/yaw/r-washout` → rudder), which
by construction passes zero rudder in a steady turn. There is no sideslip
feedback.

**Measured (B747, 3000 m, +90° heading step, 8 s steady segment at the 25°
limit).**

| | 230 kt | 300 kt |
|---|---|---|
| bank φ | 25.20° | 25.07° |
| TAS | 136.7 m/s | 177.4 m/s |
| load factor n_z | 1.1036 | 1.0986 |
| 1/cos φ | 1.1052 | 1.1040 |
| turn rate, measured | 1.761°/s | 1.325°/s |
| g·tan φ / V (coordinated) | 1.934°/s | 1.481°/s |
| radius | 4.45 km | 7.67 km |
| sideslip β (230 kt) | 1.08° | — |
| side force Y/W (230 kt) | −0.0364 | — |
| rudder command (230 kt) | −0.0012 | — |

Turn rate falls with speed as it must; load factor matches 1/cos φ to 0.15%;
radius scales as V². The 9% shortfall against g·tan φ/V is **not** a physics
error: correcting the horizontal force balance for the measured side force,
(L sin φ + Y cos φ)/W = 0.4675 − 0.0329 = 0.4346, gives ω = 0.4346·g/V =
1.786°/s at 230 kt, within 1.3% of the 1.764 measured. The aircraft is
flying a physically correct **slipping** turn because nothing coordinates it.

**External methods.** Standard coordinated-turn condition ψ̇ = g tan φ / V
holds only for zero lateral body acceleration (β ≈ 0) — see VT's
*Aerodynamics and Aircraft Performance* ch. 8 and the turn-coordination
literature. Production autopilots pair a yaw damper (washed-out r) with a
turn coordinator: either β (or lateral acceleration a_y) fed to rudder, or a
feedforward rudder proportional to the coordinated yaw rate g sin φ / V.

**Mathematical difference.** Repository: δ_r = k_r · washout(r). Coordinated:
δ_r = k_r · washout(r) + k_β · β (or k_ay · a_y), or δ_r ∝ g sin φ / V.

**Why it matters.** Every autopilot turn slips ~1°; turn rate is ~9% low for
the commanded bank, so a heading capture takes ~9% longer and the recorded
sideslip/side-force channels show an uncoordinated aircraft. For a
labeled-data product the recorded β is honest but not what a coordinated
autopilot would fly.

**Recommended direction.** Add a β→rudder (or a_y→rudder) term to the yaw
channel in `tecs.xml`, sign-measured like the other axes (`core/control/
signs.py`). One property, one gain, no architecture change.

**Sources.** tecs.xml (repo); JSBSim `aero/beta-deg`, `forces/fby-aero-lbs`;
https://pressbooks.lib.vt.edu/aerodynamics/chapter/chapter-8-accelerated-performance-turns/ ;
https://en.wikipedia.org/wiki/Yaw_damper (secondary).

### 1.2 Climb, energy, and the throttle loop

**Current repository method.** True Lambregts-form TECS: specific total
energy rate error → throttle (`kt-p` 1.2, `kt-i` 0.30), energy balance rate
error → pitch (`ke-p` 0.5, `ke-i` 0.08), one time constant τ = 5 s, both
errors normalised by g·V, anti-windup on actuator saturation. Rate limits
`hdot-max` 40 ft/s, `vdot-max` 6 ft/s².

**Measured (B747, 250 kt, 3000 → 3300 m step).**

| | value |
|---|---|
| climb rate, steady | 3.93 m/s (≈ 770 ft/min) |
| TAS during climb | 148.16 → 148.16 m/s (held to 1 cm/s) |
| θ before → during | 3.73° → 5.26° |
| α before → during | 3.73° → 3.72° (unchanged: pure flight-path change) |
| throttle before → during | 0.579 → 0.653 |
| T/W used | 0.126 ; T/W at full throttle 0.297 |
| fraction of available excess power used | **0.54** |
| overshoot | 9.5 m (3.2% of step) |
| time to capture | ≈ 75 s |

Causality is exactly right: throttle rises, thrust exceeds drag, the energy
goes into altitude at constant airspeed because the pitch loop redistributes
it (α unchanged, γ = θ − α rose 1.5°). Nothing is imposed.

But the loop is far slower than its τ implies. With τ = 5 s the demanded
initial climb rate is 60 m/s (clipped to 12 m/s); the aircraft climbed at
3.9 m/s and used barely half the airframe's excess power. Cause: the
throttle command is (Ė_err/(gV)) × k_t. Physically Ė_err/(gV) is the
required ΔT/W, so the throttle needed is ΔT/W ÷ (T_max/W) — for the B747
(T_max/W ≈ 0.30) the gain should be ≈ 1/0.30 ≈ 3.3, not 1.2. The same file
on the c172p (T_max/W ≈ 0.12 at cruise) would need ≈ 8.

**Cross-airframe measurement (same `tecs.xml`, 100 m step, sign probe
primed at a reachable state for the c172p — see 3.1).**

| | c172p, 85 kt, 600 m | B747, 250 kt, 3000 m |
|---|---|---|
| time to 90% | 26.9 s | 23.9 s |
| peak climb rate | 4.72 m/s (929 ft/min) | 4.36 m/s (858 ft/min) |
| throttle trim → peak | 0.632 → **0.981** | 0.579 → 0.682 |
| fraction of excess thrust used | **0.74** | **0.17** |
| overshoot | 7.5 m | 9.3 m |

The same gain drives the Cessna to 98% throttle and the 747 to 17% of
its excess thrust. The rise times look alike only because the small
airframe is throttle-saturated, not because the loop is tuned; the 747
has four times the excess power it is allowed to use.

**External methods.** ArduPilot AP_TECS normalises exactly this:
`K_thr2STE = (STEdot_max − STEdot_min)/(THRmax − THRmin)`, where
STEdot_max = g·(max climb rate) and STEdot_min = −g·(min sink rate) are
*measured airframe capabilities*, so throttle bandwidth is airframe-invariant.
Lambregts' TECS (NASA TSRV flight tests, NTRS 19870017485) likewise scales
the throttle path by thrust-to-weight so the same gains transfer between
airplanes.

**Mathematical difference.** Repository: δ_thr = k_t · Ė_err/(gV).
Reference: δ_thr = Ė_err / (τ · (Ė_max − Ė_min)) · (thr_max − thr_min), with
Ė_max, Ė_min from a performance model.

**Why it matters.** Climb capture is 2–3× slower than the airframe; the
loop's bandwidth differs per airframe with the same gains; and a terrain
look-ahead that asks for a climb will get a fraction of what the aircraft
can do. The **deeper root cause is shared with the terrain gap: the
repository has no airframe performance model** (max climb rate, min sink
rate as a function of mass, density, speed). The TECS normalisation and
the predictive-clearance feasibility check both need the same object.

**Recommended direction.** Add `core/performance.py` measuring Ė_max and
Ė_min from the FDM at the trimmed state (the `envelope.measure_lift_curve`
pattern), write them as `ap/tecs/stedot-max` / `-min` at engage, and
normalise the throttle path by them. Then the same performance object feeds
the terrain look-ahead (Cycle 3).

**Sources.** tecs.xml header (repo); ArduPilot `AP_TECS.cpp`
(`_update_throttle_with_airspeed`, `_update_STE_rate_lim`) —
https://raw.githubusercontent.com/ArduPilot/ardupilot/master/libraries/AP_TECS/AP_TECS.cpp ;
NASA TECS flight test, NTRS 19870017485 (index page reachable; PDF blocked
from this environment); Lambregts TECS update, Springer 978-3-642-38253-6_30.

### 1.3 Numerical integration and timestep

**Current repository method.** JSBSim's integrators at a fixed rate from the
spec (120 Hz default, chosen to match the UE plugin substep). The repository
does not override JSBSim's defaults, which are (FGPropagate.cpp,
constructor/InitModel): rotational rate **rectangular Euler**, rotational
position **rectangular Euler** (quaternion, normalised after each step),
translational rate **Adams–Bashforth 2**, translational position
**Adams–Bashforth 3**; state propagated in ECI and transformed to ECEF.
Rendering FPS is a separate encode constant and never touches integration.

**Measured (B747 open-loop aileron doublet, 22 s, identical inputs).**

| rate | Δψ vs 240 Hz | Δh | ground-track Δ |
|---|---|---|---|
| 60 Hz | 0.0013° | 1.7 mm | 0.117 m |
| 120 Hz | 0.00045° | 0.5 mm | 0.039 m |
| 240 Hz | — | — | — |

Halving dt reduces the error by ~3×: consistent with the mixed
first/second-order scheme. Frame-rate independence is total; a 60 Hz run
lands within 12 cm of a 240 Hz run after 22 s.

**External methods.** JSBSim offers AB3/AB4/Buss/local-linearisation for
the rotational integrators; FlightGear ships JSBSim with these defaults.

**Why it matters / direction.** No change needed. The rotational Euler
integrators are the weakest link, but at 120 Hz with the attitude rates a
transport flies they are converged to millimetres. Do not spend effort here.

**Sources.** https://github.com/JSBSim-Team/jsbsim/blob/master/src/models/FGPropagate.cpp ;
https://jsbsim-team.github.io/jsbsim/classJSBSim_1_1FGPropagate.html

### Cycle 1 — iteration record

**New findings.** (1) Turns are uncoordinated: yaw damper without turn
coordination, β ≈ 1°, ω 9% below coordinated. (2) TECS throttle path is
not normalised by airframe performance: climb uses 54% of available
excess power, gains are not airframe-transferable. (3) Timestep
independence verified to 0.1 m / 22 s.

**Deeper root causes.** Finding (2) and the terrain look-ahead gap (prior
audit, P1) share one root: **no performance model** exists. Finding (1) is
a missing term, not a missing model.

**Research completed.** Lambregts/NASA TECS structure; ArduPilot TECS
normalisation; JSBSim FGPropagate integrator defaults and ECI propagation;
coordinated-turn kinematics and turn-coordination practice.

**New mathematical connections needed.** performance(mass, ρ, V) →
{Ė_max, Ė_min} → TECS throttle normalisation AND terrain feasibility.
β (or a_y) → rudder.

**Questions for Cycle 2.** Does steady wind produce a physically correct
crab at trim, and does wind enter aerodynamics only through
`atmosphere/wind-*` (air-relative) or anywhere as a position push? What is
the orographic vertical-wind model and is it a recognised one? Does ERA5
set temperature/pressure (density altitude) or only wind? How is Dryden
turbulence scaled with altitude in JSBSim and in `turbulence.py`?

---

## Cycle 2 — wind, initialisation, environment coupling

### 2.1 Wind enters aerodynamics correctly — but the aircraft is never trimmed in it

**Current repository method.** `core/scenario/runner.py:configure_from_spec`
writes `atmosphere/wind-{north,east,down}-fps`, then calls `start_engines()`
and `trim()`, with the docstring "Steady wind is written before trim so the
aircraft is trimmed *in* the conditions it will fly." `EnvironmentStack.apply`
then rewrites the wind every step. The engine host (`FlightSimScenarioWorld.cpp:
TrimInWind`) reproduces the same sequence and logs "re-trimmed in N kt wind".

**Measured.** The wind does not survive `trim()`.

| stage | `atmosphere/wind-east-fps` (30 kt crosswind) |
|---|---|
| after `set_many` | −50.63 |
| after `start_engines` | −50.63 |
| after `trim()` | **0.00** |
| after raw `do_trim(1)` alone | **0.00** |

Mechanism, confirmed from source: `FGTrim::DoTrim()` calls
`fdmex->Initialize(&fgic)`, which re-applies every initial condition —
including the zero wind IC — over the direct property writes. Both hosts
therefore trim in calm air, and the crosswind "FULL" trim solves with
rudder = aileron = β = 0, identical to calm. When the run loop then writes
the wind on step 1, the aircraft receives a **wind step from a calm trim**.

Consequence, open loop (the render host's only mode, B747, 250 kt, 3000 m,
30 s):

| case | ΔTAS at t=0 | altitude excursion | note |
|---|---|---|---|
| headwind 30 kt | +30 kt | **+333 m** | zoom into a phugoid |
| tailwind 30 kt | −30 kt | **−327 m** | dive into a phugoid |
| crosswind 30 kt | β step 5.95° | 2 m; φ peak 4.6°, crab 5° emerges | benign in altitude |

Consequence, closed loop (TECS on, headwind 30 kt, 60 s): CAS steps to
276 kt, altitude balloons +44.5 m at 10 s, throttle slams 0.58 → 0.14, and
the altitude band over the last 30 s is still 39 m — outside the closure
tolerance of 15 m unless the run is long enough to settle.

**The repository has already observed this and misdiagnosed it.**
`tests/test_host_parity.py::test_the_trim_snapshot_is_not_graded_but_the_flight_is`
records a 13 kt headwind case whose first sample reads 288 kt TAS against
301 kt one sample later, attributes it to the recorder sampling "before the
environment loop runs", and exempts that sample from parity grading. The
sample reads 288 because the *trim state* is calm; the switch-on artefact
is the physics, not the recorder. Both hosts agree afterwards because both
share the flaw — parity is not correctness.

Physics sanity check: the crab, the groundspeed/airspeed split and the
weathercocking all emerge correctly once wind is present (crosswind:
heading 2.97° vs track 357.98°; headwind: GS 124.7 vs TAS 140.4 m/s). The
coupling is real; only the initialisation is wrong.

**External methods.** JSBSim's own wind initial conditions (`ic/vw-mag-fps`,
`ic/vw-dir-deg` — *direction the wind blows toward*, measured: dir 90 →
+east) hold the ground velocity and re-derive airspeed (FGInitialCondition:
`_vt_NED = vUVW_NED + wind; vt = |_vt_NED|`). The engine host's authors hit
exactly this ("a commanded 250 kt CAS comes out of RunIC at 206 kt") and
fell back to the same post-trim property write.

**Proof of concept (this audit).** With wind in FGWinds *and* the
air-relative state made consistent with it before `trim()`, the transient
disappears:

| case | open-loop 30 s altitude excursion | closed-loop 60 s |
|---|---|---|
| headwind 30 kt, today | 333 m | 44 m balloon, 39 m band |
| headwind 30 kt, trimmed in wind | **1.4 m** | **0.02 m** |
| tailwind 30 kt, today | 327 m | — |
| tailwind 30 kt, trimmed in wind | **0.6 m** | — |

Naive use of the JSBSim IC route is *worse* than today: the airspeed comes
out at 303/197 kt for 250 commanded, and a crosswind IC trims into a 29°
banked, 12° sideslip, rudder-0.87 "equilibrium". The fix must therefore be
a **fixed-point on the observed air-relative state**: set wind, `run_ic`,
read (vc, β), adjust the ground-speed and heading ICs by the discrepancy,
repeat until vc = commanded and β = 0, then trim. Linear, converges in
one or two iterations, semantic-independent — the same "measure rather
than assume" discipline `_IC_PRIORITY` already applies.

**Why it matters.** Every windy scenario the project renders begins with a
transient the spec did not ask for. Open loop that transient is hundreds
of metres over a 22 s clip: a "level flight in a 30 kt headwind" clip
climbs ~250 m. This is precisely the failure the closure assertion was
built to catch, on precisely the path it cannot reach.

**Recommended direction.** (1) Fix initialisation as above in
`configure_from_spec` and mirror it in `TrimInWind`. (2) Delete the
first-sample exemption in the parity test once the trim snapshot carries
the wind — the exemption is currently hiding the defect. (3) Add a guard:
after trim in a wind spec, `atmosphere/total-wind-*` must equal the spec
wind and `velocities/vc-kts` the spec airspeed, or refuse by name.

**Sources.** FGTrim.cpp (`DoTrim` → `Initialize(&fgic)`):
https://github.com/JSBSim-Team/jsbsim/blob/master/src/initialization/FGTrim.cpp ;
FGInitialCondition.cpp (`SetWindNEDFpsIC`):
https://github.com/JSBSim-Team/jsbsim/blob/master/src/initialization/FGInitialCondition.cpp ;
FGInitialCondition reference:
https://jsbsim.sourceforge.net/JSBSim/classJSBSim_1_1FGInitialCondition.html ;
repo: `tests/test_host_parity.py:109`, `ue/.../FlightSimScenarioWorld.cpp:947,1073`.

### 2.2 Turbulence, orographic field, atmosphere

**Turbulence.** Driven through JSBSim's own MIL-F-8785C Dryden filters at
FDM rate (`core/environment/turbulence.py`); the repository *measured* the
two regimes (σ_w = 0.107·W20 below 1000 ft; POE index above) rather than
assuming them, and refuses unknown intensity words. This is the correct
division: a Python re-implementation would run at harness rate. No change.

**Orographic vertical wind** (`core/environment/terrain_field.py`). The
linearised lower boundary condition w = U·∇h (Smith 1979; Queney 1948),
saturated above slope 0.35, decaying as exp(−z/H) with H = L/2π — the
neutral potential-flow solution — plus an explicit lee sink (×1.3 the
windward ascent) and rotor turbulence. Limits are stated in the file: no
Froude number, no stability, separation assumed wherever a crest is
upstream. This is a recognised first-order model, honestly labelled.
*Fidelity note (P3):* in stratified air (the real case over mountains,
Scorer parameter l² > 0) the perturbation does not decay with height; it
propagates as a mountain wave. The model chooses the N = 0 limit, so it
understates vertical wind at cruise altitudes downwind of ridges. Not a
coupling failure — a stated approximation.

**Atmosphere.** `base.py` defines `AtmosphereProvider` (temperature and
pressure deviations) — **no concrete subclass exists**. ERA5 supplies wind
at the nearest pressure level only. Density is always ISA at the given
altitude: a hot day over a high plateau does not degrade climb or raise
TAS for a given CAS. Missing coupling, P3 — the seam is built, nothing
plugs into it.

**Sources.** JSBSim FGWinds (MIL-F-8785C):
https://jsbsim.sourceforge.net/JSBSim/classJSBSim_1_1FGWinds.html ;
AMS glossary, Scorer parameter: https://glossary.ametsoc.org/wiki/Scorer_parameter ;
OU mountain-forced flows (ch. 2): https://twister.caps.ou.edu/MM2005/Chapter2.1_2007.pdf

### Cycle 2 — iteration record

**New findings.** (4) Neither host trims in wind; every windy run starts
with a wind step; open-loop clips drift hundreds of metres. (5) The
repository's parity test exempts the exact sample that reveals it.
(6) No atmosphere provider exists; density altitude is never non-standard.

**Deeper root causes.** (4) is a JSBSim initialisation-order interaction of
the same family `_IC_PRIORITY` already documents — the repository knew the
class of problem and missed this instance. (5) is the P0 host-asymmetry
finding seen from the other side: with no controller on the render host,
there is nothing to absorb the step.

**Research completed.** FGTrim/FGInitialCondition semantics; JSBSim
Dryden implementation; orographic linear theory and its stratified limit.

**New mathematical connections needed.** Trim state ⇄ wind (fixed point);
temperature/pressure deviation → density → performance (provider exists,
unfilled).

**Questions for Cycle 3.** How much does the turbulence the clearance plan
omits actually move the minimum clearance? What look-ahead law fits the
setpoint interface that exists? Does the parity harness's tolerance table
even include the channels these findings show up in?

---

## Cycle 3 — terrain look-ahead, guidance feasibility, the sign probe

### 3.1 Why the c172p can never engage the autopilot

**Current repository method.** `Autopilot.engage()` calls
`core/control/signs.py:measure(base)`, which builds a *throwaway* instance
of the stock airframe, trims it, pulses each control and reads the sign of
the resulting body rate — the right idea (a hardcoded convention "closes
the loop with positive feedback"). The probe condition is hardcoded:
**6000 m, 280 kt CAS** (`measure(aircraft, altitude_m=6000.0, cas_kt=280.0)`).

**Measured.** The c172p trims fine with the TECS system attached, at
600 m/85 kt, 1200 m/100 kt and 300 m/75 kt, through the runner's own
`configure_from_spec`. `Autopilot.engage()` then fails every time —
`TrimFailureError` inside `signs.measure` — because a Cessna 172 cannot fly
280 kt at 6000 m (V_NE ≈ 163 kt, service ceiling ≈ 4 km). The earlier
session's "c172p TrimError with hold_state" was this.

**Why it matters.** The closed-loop path — and with it the closure
assertion, TECS, and every finding above about the controller — is
reachable only for airframes that can hold a transport-category probe
state. The general-aviation airframe is silently open-loop-only.

**Fix demonstrated.** `signs.measure("c172p", altitude_m=600, cas_kt=85)`
primes the cache at a reachable state; `engage()` then succeeds and the
c172p flies a closed-loop altitude step (table in 1.2). Measured signs:
+elevator = nose down, +aileron = roll right, +rudder = yaw left — the
convention is indeed condition-independent, as the file claims.

**Recommended direction.** Probe at the spec's own trimmed state (the
aircraft is already there when `engage()` runs — pulse *it*, or a copy of
it), or at the airframe's measured cruise from `envelope.reference_speeds`.
The convention is "a property of the flight control section, not of the
flight condition" (the file's own words), so any trimmable condition is
valid. One-line change, removes a whole-airframe exclusion.

**Sources.** `core/control/signs.py:76–135`.

### 3.2 Terrain look-ahead: what exists, what the standards do, what fits

**Current repository method.** Terrain has two consumers in the loop
(`TerrainGround.apply` → AGL/ground reactions; `AirframeContact.check` →
raise on impact) and one at plan time (`plan_terrain_flight` pre-flies the
scripted track on the raster, raises a *defaulted* altitude to
peak + 30 m, refuses a *stated* one by name). Nothing samples the raster
ahead of the aircraft during a run; nothing knows the airframe's climb
capability; nothing can command a climb.

**External methods.** TAWS Forward-Looking Terrain Avoidance (RTCA DO-367
MOPS; FAA TSO-C151/EASA ETSO-C151) projects the flight path along a
"sensor profile" of two or more segments — a *response segment* (the path
flown for a reaction time at the current velocity vector) followed by a
*climb profile* (a climb gradient the aircraft is assumed able to fly) —
against a terrain database within a search volume of a look-ahead
distance and a lateral half-width, comparing against a Required Terrain
Clearance that depends on flight phase, with caution and warning
look-ahead times. Automatic GCAS (Auto-GCAS) goes one step further: it
integrates an *escape manoeuvre* (roll to wings level at the airframe's
roll rate, pull to its load-factor limit, climb at its capability) and
triggers when the escape trajectory's clearance reaches the floor. In both
cases the aircraft's *performance model* is an input, and a threat is
decided *before* the terrain is reached.

**Mathematical difference.** Repository: clearance(t) = h(t) − z(x(t)),
checked at t only, and at plan time along a scripted track. Standard:
min over s ∈ [0, T] of [h_pred(s) − z(x_pred(s))] − RTC, where h_pred
follows the response segment then a climb at γ_avail = asin((T−D)/W).

**Why it matters.** A ridge the pre-flight cleared by 30 m and a run
crossing it 20 m lower (turbulence, wind change, a different script) ends
the run with `TerrainImpactError` after the render. The aircraft cannot
fly over anything it did not plan over.

**Recommended direction.** An `EnvironmentStack`-style consumer that, at
guidance rate (2 Hz), samples the raster along the projected ground track
for T ≈ 60–90 s, computes required Ė = g·(z_ahead + RTC − h)/t_ahead, asks
the performance model for Ė_max at the current state, and either ramps
`ap/altitude-setpoint-ft` (the interface exists and is tested) or refuses
by name. This is the terrain analogue of `plan_terrain_flight`, moved from
plan time into the loop, using the same raster lookup and the same span
stations. It needs the performance model of 1.2 — the same object.

**Sources.** RTCA DO-367 (MOPS for TAWS) — index:
https://standards.globalspec.com/std/10163143/RTCA%20DO-367 ;
EASA ETSO-C151d (FLTA definition, index only reachable):
https://www.easa.europa.eu/download/etso/ETSO-C151d.pdf ;
FAA/DOT Part-23 Auto-GCAS report (index only reachable):
https://rosap.ntl.bts.gov/view/dot/79347/dot_79347_DS1.pdf .
The authoritative PDFs are blocked from this environment; the structure
above is taken from their indexed summaries and from the patent
literature on FLTA sensor profiles.

### 3.3 Path following, if routes are ever wanted

**Current repository method.** None. Heading hold only.

**External methods.** Park–Deyst–How nonlinear guidance (L1), as
implemented in ArduPilot `AP_L1_Control.cpp`:
`L1_dist = (1/π)·ζ·T·V_ground`, `a_lat = 4ζ²·V_ground²/L1_dist·sin η`,
η = η₁ + η₂ with sin η₁ = cross-track/L1 and η₂ = atan2(v_xtrack, v_along),
then `φ_dem = atan(a_lat / (g·cos θ))`. It uses **ground** speed so wind is
handled implicitly, reduces to a PD law on cross-track for straight legs
and anticipates curvature on arcs. The bank demand lands on exactly the
`ap/bank-setpoint-rad` / `ap/bank-mode` interface `tecs.xml` already
exposes.

**Recommended direction.** Only if routes are in scope. If so, L1 above
the existing bank-hold is the whole lateral guidance layer — ~100 lines,
no physics change, and the 25° bank limit already bounds a_lat.

**Sources.** Park, Deyst, How, "A New Nonlinear Guidance Logic for
Trajectory Tracking", AIAA GNC 2004 (PDF blocked; law taken from the
ArduPilot implementation):
https://raw.githubusercontent.com/ArduPilot/ardupilot/master/libraries/AP_L1_Control/AP_L1_Control.cpp

### 3.4 The clearance plan under the run's own turbulence — a null with a cause

**Set-up.** The webapp's own planner chain on the synthesised control
ridge: `plan_scene_setting → place_on_scene → apply_weather_event →
plan_terrain_environment → derive_seed → plan_terrain_flight` for "fly
the 747 through the mountains at 250 kt with a 30 kt wind". The planner
raised the defaulted altitude to 3384 m (peak + `PLANNED_CLEARANCE_M` =
300 m); wind 30 kt from 092°, heading 002° (along-ridge, planned). The
scripted doublet was then flown (a) as `_fly_clearance_track` does —
orographic sink, no turbulence — and (b) with the `LeeRotorTurbulence`
provider the real run carries, for four seeds.

| | minimum span-station clearance |
|---|---|
| plan (no turbulence) | 297.7 m |
| run, seeds 65598 / 1 / 2 / 3 | 297.7 / 297.7 / 297.7 / 297.7 m |
| difference | **0.0 m** |

**Why zero, traced.** Recording the total vertical wind with and without
the rotor gave identical standard deviations (1.151 m/s, all orographic):
**the rotor delivered no turbulence at all.** Three measurements explain
it:

1. `LeeRotorTurbulence.step_writes` returned W20 = 0 along the whole
   track — the coupling is W20-only and, by construction, inert above
   `LOW_ALTITUDE_CEILING_M` = 300 m AGL. The planner's margin is
   `PLANNED_CLEARANCE_M` = 300 m. **The planner keeps every track at or
   above the rotor's ceiling**, so on planner-produced scenes the rotor
   coupling can never act.
2. Above the ceiling the provider claims "the constant POE index-1 floor,
   1.785 fps" (`expected_sigma_w_mps` returns 0.544 m/s). JSBSim's
   MIL-F-8785C at severity 1, W20 = 0, terrain 0, gives σ_w = 0.0 fps at
   150–300 m, 0.91 at 450, 1.51 at 600, 1.21 at 1000, 0.76 at 1500 m —
   not constant, and altitude-dependent through the high-altitude table.
3. **With terrain elevation set, the floor vanishes.** Same 500 m AGL:
   terrain 0 → σ_w 1.12 fps; terrain 2500 m → **0.0 fps**, calm or in
   30 kt wind. JSBSim's high-altitude branch indexes MIL-F-8785C Fig. 7
   by *MSL* altitude, and the 10⁻¹-exceedance ("severity 1") curve is
   zero at ~3000 m MSL. Severity 3 at the same MSL still delivers
   (4.6 fps), so the branch is live — it is the index-1 curve that is
   zero there.

**Conclusion.** On a mountain run — the only scene that carries a rotor —
the aircraft flies ≥300 m AGL at ~3000 m MSL, where the W20 route is
inert by design and the POE-1 "floor" is zero by the standard. The
"lee-rotor turbulence" that `coupling_needs_seed` seeds, `card_word`
advertises as `lee-rotor`, and the conditions strip reports, delivers
**no turbulence** in the regime the planner produces. `tests/test_rotor.py`
asserts the provider's *claimed* floor value, not the FDM's delivered
one, so nothing caught it. Finding #8 (plan omits turbulence) is
therefore immaterial as stated and is replaced by this one.

**Recommended direction.** Either lower the rotor's ceiling assumption to
match where the W20 route really governs and drive the *severity* index
(not W20) above it from the lee-sink field — JSBSim accepts a constant
severity at configure time — or state plainly in provenance that rotor
turbulence acts only below 300 m AGL and is absent on planned tracks.
Add a null test that measures delivered σ_w at the planned altitude and
refuses to label a run `lee-rotor` when it is zero.

**Sources.** `core/environment/rotor.py:12–26,113–170`; `webapp/runs.py:
PLANNED_CLEARANCE_M`; JSBSim FGWinds MIL-F-8785C implementation:
https://jsbsim.sourceforge.net/JSBSim/classJSBSim_1_1FGWinds.html

### Cycle 3 — iteration record

**New findings.** (7) Sign probe hardcoded at 6000 m / 280 kt excludes
the c172p from closed-loop flight. (8) Terrain look-ahead is absent and
the standard formulation needs the same performance object as TECS.
(9) The lee-rotor turbulence coupling delivers zero turbulence on every
planner-produced mountain track: W20 route inert ≥ 300 m AGL, POE-1 floor
zero at ~3000 m MSL, and the provider's own null-test value is wrong there.

**Deeper root causes.** (7) and the wind-trim defect (4) are the same
species: a fixed condition assumed rather than the spec's measured one.

**Research completed.** DO-367/ETSO-C151 FLTA structure; Auto-GCAS escape
projection; L1 guidance law and its ArduPilot form.

**Questions for Cycle 4.** Do the two hosts share every frame convention?
What does the parity harness actually bound, and does its tolerance table
include the channels that would expose these findings?

---

## Cycle 4 — frames, hosts, what parity proves

**Frames traced.** Geodetic lat/lon (JSBSim `position/lat-geod-deg`,
`long-gc-deg` — longitude is identical in both conventions; latitude is
geodetic, correct for a WGS-84 raster) → projected metric CRS via pyproj
(`TerrainGround.project`; `SceneFrame.for_spec` uses the *raster's* CRS on
a terrain scene and the origin's UTM zone otherwise, so cameras, contact
and orographic field share one frame) → local north/east about the card
origin → engine: `ProjectedToEngine`, yaw_engine = heading − 90° (UE yaw 0
is east), and the inverse `EngineToProjected`, heading = yaw + 90°, used
consistently in both directions of the commandlet. Aerospace intrinsic
Z-Y′-X″ Euler for pose capture; JSBSim quaternion inside. No mixed-frame
force application found; no gimbal exposure in user code.

**What the parity harness bounds.** `experiments/gate5_ue_parity.py`
compares altitude (5 m), TAS (2 kt), roll/pitch/heading (1°), n_z (0.05),
lat/lon (1e-4°, ≈11 m) between hosts after the first sample. Both hosts
run the same JSBSim 1.2.4 at 120 Hz, so agreement to these tolerances
proves the *integration* matches — and, as Cycle 2 shows, it proves
nothing about initialisation correctness, because both hosts initialise
identically. Parity is necessary, not sufficient.

**Timestep.** Cycle 1: 60/120/240 Hz agree to 0.12 m over 22 s.

**Cycle 4 — iteration record.** No new frame defects. The audit's
remaining open item is the pending turbulence-in-plan measurement.
