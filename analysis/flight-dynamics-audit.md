# Airborne physics audit and reconstruction plan

Repository `DhruvaValluru/flightsim`, commit `e73aee8`. Companion files:
`flight-dynamics-research-ledger.md` (every measurement, every source,
cycle by cycle) and `mathematical-dependency-map.md` (every coupling).
All numbers here were produced by running the repository's own physics
headlessly during the audit; the scripts are reproduced in the appendix.

## Executive answer

**What makes the aircraft move is JSBSim, and nothing else.** One
integrator, one writer of physical state (`fdm.step()`), fixed 120 Hz,
frame-rate-independent to 12 cm over 22 s between 60 and 240 Hz. Lift,
drag, thrust, gravity and mass are all real and all consumed; angle of
attack is distinguished from attitude; wind enters as air-relative
velocity; bank produces turns through tilted lift with load factor
matching 1/cos φ to 0.15%; climb comes from thrust exceeding drag with
airspeed held to 1 cm/s by a genuine total-energy controller; fuel burn
moves mass. There is no fake physics anywhere. Fidelity: **nonlinear
6-DOF (Level E)**, already beyond what this project needs.

**The defects are all at the boundaries of that physics** — initial
conditions, control-law normalisation, one missing coupling, and the
asymmetry between the two hosts:

| # | finding | severity | evidence |
|---|---|---|---|
| 1 | The render host has no controller; every clip is open loop and the closure assertion never runs on it | **P0** | `project_for_ue_host` |
| 2 | Neither host trims *in* the wind: `FGTrim::DoTrim` re-applies zero wind ICs; every windy run starts with a wind step. Open loop: ±330 m in 30 s. Closed loop: 44 m balloon, 39 m band at 60 s. Proven fixable: 1.4 m / 0.02 m when trimmed in wind | **P0** | measured, Cycle 2 |
| 3 | The repository saw #2 (288 kt vs 301 kt first sample) and exempted the sample from parity grading instead of fixing the trim | P0 (masks #2) | `test_host_parity.py:109` |
| 4 | No terrain look-ahead; terrain's only in-flight action is to end the run | P1 | Cycle 3 |
| 5 | No airframe performance model; TECS throttle gain is a fixed 1.2 → climb uses 54% of excess power, 75 s for 300 m, non-transferable across airframes | P1 | measured, Cycle 1 |
| 6 | Control-sign probe hardcoded at 6000 m / 280 kt → the c172p can never engage the autopilot | P1 | measured, Cycle 3 |
| 7 | Turns are uncoordinated: yaw damper without turn coordination; β ≈ 1°, ψ̇ 9% below g·tan φ/V (explained to 1.3% by the measured side force) | P2 | measured, Cycle 1 |
| 8 | The advertised lee-rotor turbulence delivers **zero** turbulence on every planner-produced mountain track (W20 route inert ≥300 m AGL = the planner's margin; POE-1 floor is 0 at ~3000 m MSL; the provider's null-test value claims 0.54 m/s there) | P1 | measured, Cycle 3 |
| 9 | No atmosphere provider: density altitude always ISA | P3 | `base.py` |
| 10 | Orographic field uses the neutral (non-propagating) limit | P3 | `terrain_field.py` |

**Fix first:** #2 and #6 (both are initialisation-condition mistakes with
one-function fixes and measured proofs), then #1 by pairing every render
with an asserted closed-loop headless run, then #5 and #4 together
because they need the same new object — a performance model measured
from the FDM the way the lift curve already is.

---

## 1. Current airborne architecture

```
spec ─▶ validate ─▶ configure_from_spec (ICs, wind, trim) ─▶ [engage TECS]
  ─▶ loop @120 Hz: environment.apply · terrain.apply · fdm.step · contact.check · [ap.update @2 Hz] · record @10 Hz
  ─▶ closure assertion (headless only) ─▶ digest, manifest, telemetry
```
Two hosts consume one card: the headless runner (`core/scenario/runner.py`)
and the Unreal commandlet (`ue/.../FlightSimScenarioWorld.cpp`), both
embedding JSBSim 1.2.4 at 120 Hz. Guidance (`core/control/autopilot.py`)
writes only `ap/*-setpoint-*`; the control laws (`core/control/systems/
tecs.xml`) run inside the FDM at integrator rate. Environment providers
(`core/environment/*`) are pure functions of (position, time) summed into
JSBSim's wind properties; turbulence is JSBSim's own MIL-F-8785C Dryden.
Terrain (`core/terrain/*`) feeds the FDM's ground elevation from a
georeferenced raster through pyproj, and checks span stations each step.

## 2. Actual state-propagation pipeline

See `mathematical-dependency-map.md` §1. The authoritative state vector is
JSBSim's: ECI position and velocity, body-to-ECI quaternion, body rates,
plus fuel mass. Derived: NED velocity, α, β, q̄, CAS/TAS, AGL. Commands:
six `ap/*` setpoints. Environment inputs: three wind components, W20,
terrain elevation. Controller states: TECS integrators (inside JSBSim).

**State-ownership matrix (real).**

| variable | JSBSim | Autopilot | Environment | Terrain | webapp planners | Renderer |
|---|---|---|---|---|---|---|
| position, velocity, attitude, rates | WRITE | read | read (position) | read | — | read |
| mass / fuel | WRITE | — | — | — | `hold_mass` flag (pre-run) | — |
| control surfaces | WRITE (FCS) | setpoints only | — | — | script deltas (pre-run card) | read |
| wind, turbulence | read | — | WRITE | — | — | — |
| terrain elevation under a/c | read | — | — | WRITE | — | — |
| initial conditions | read | — | — | — | WRITE (spec edits, recorded) | — |

No multi-writer of physical state exists. The only questionable cell is
the planners' pre-run edits, which are recorded spec transformations, not
runtime writes.

## 3. Actual vs ideal dependency graph

`mathematical-dependency-map.md` §3 (actual) and §4 (ideal). Nine intact
couplings; the severed or absent ones are: terrain→guidance, performance→
{TECS, guidance}, turbulence→clearance plan, wind→trim state, control→render
host, fuel→render host, T/P deviation→density, β→rudder.

## 4. Broken mathematical couplings

```
Wind exists                         BUT the trim state does not contain it (both hosts).
Terrain ahead is queryable          BUT no subsystem queries it during flight.
Excess power is computable          BUT neither TECS nor any planner asks for it.
Sideslip is measured every step     BUT no control law consumes it.
Turbulence is seeded before planning BUT the clearance plan flies without it.
The TECS controller exists          BUT the render host does not carry it.
Fuel burn moves mass                BUT every rendered run freezes it.
The atmosphere provider seam exists BUT nothing implements it.
Control signs are measured          BUT at a state the c172p cannot reach.
```

## 5. Fake physics

None. Repository-wide, the only write into `position/*`, `velocities/*`
or `attitude/*` outside tests is `position/terrain-elevation-asl-ft`
(`core/terrain/ground.py:75`), a ground-truth input. `hold_mass` is an
opt-in, provenance-recorded experimental control. The scripted aileron
doublet is a pilot input applied as a delta on the trimmed surface.

## 6. Translational dynamics

JSBSim: ΣF = ma in the body frame with aero (tables), propulsion, gravity
(WGS-84), ground reactions; velocities integrated in ECI with
Adams–Bashforth 2, positions with AB3. Measured: fuel-burn altitude drift
+89.6 m / 400 s (repo), 60↔240 Hz trajectory agreement 12 cm / 22 s
(audit). No change needed.

## 7. Rotational dynamics

JSBSim: ω̇ = I⁻¹(M − ω×Iω), quaternion attitude, rectangular Euler
integration of rates and quaternion at 120 Hz with renormalisation.
Turns: heading → bank (≤25°) → roll rate → aileron, all at 120 Hz. Load
factor 1.1036 at 25.2° bank (theory 1.1052); radius 4.45 km at 230 kt,
7.67 km at 300 kt. **Coordination is missing:** the yaw channel is a
washed-out rate damper only; steady β = 1.08°, side force −3.6% W,
turn rate 1.76°/s vs 1.93°/s coordinated. Recommended level: **keep 6-DOF;
add one β→rudder term.**

## 8. Aerodynamics

C_L, C_D, C_m and stability derivatives are the aircraft XML tables of
the stock JSBSim models (B747, A320, c172p, …). The repository does not
assume a lift curve — it *measures* C_L(α) from the model
(`envelope.measure_lift_curve`) to derive stall and reference speeds for
validation. Density is JSBSim's ISA at altitude; TAS/CAS conversion is
measured at the current state in the guidance loop rather than from a
formula. Nothing to add.

## 9. Energy and performance

TECS is a true Lambregts form (Ė → throttle, energy balance → pitch, one
τ). Measured on a 300 m step: throttle 0.58 → 0.65, TAS constant to
1 cm/s, α unchanged, γ +1.5° — energy is conserved and redistributed
correctly. But the throttle path uses a fixed gain on Ė_err/(gV): the
airframe's T_max/W never enters, so the B747 climbed at 3.9 m/s using
54% of available excess power and took 75 s; on a 100 m step it used 17%
while the same file drove the c172p to 98% throttle (74% of its excess).
ArduPilot and Lambregts both
divide by the measured (Ė_max − Ė_min). **The performance model is the
missing object**, and it is also what terrain look-ahead needs.

## 10. Atmosphere and wind

Wind: correct once present (crab 5° emerges in a 30 kt crosswind; GS/TAS
split correct; weathercocking correct). **Initialisation is wrong on
both hosts** (finding #2; proof of fix in ledger 2.1). Turbulence:
JSBSim Dryden, both MIL-F-8785C regimes measured. Orographic: linear
lower boundary condition with neutral decay — recognised, limits stated,
understates mountain-wave amplitude aloft (P3). Atmosphere deviations:
seam exists, unimplemented (P3).

## 11. Guidance and control

Navigation: absent (no route, no waypoints). Guidance: setpoints only,
2 Hz, CAS→TAS ρ-correction — correct division. Control: cascaded TECS +
heading/bank/roll-rate + yaw damper, bumpless engage, measured sign
convention, anti-windup on saturation, 25° bank limit. Defects: throttle
normalisation (#5), no turn coordination (#7), sign probe condition (#6).
Guidance **can** request impossible manoeuvres: nothing checks a
commanded altitude against climb capability or a commanded heading
against turn radius versus terrain — only bank is limited.

## 12. Terrain and predictive clearance

Plan time: real pre-flight on the raster, span-station minimum,
orographic sink included, turbulence excluded. Run time: elevation under
the aircraft (correct), impact detection every step (1.07 m spacing at
250 kt against 30 m pixels — no tunnelling), no look-ahead, no avoidance.
Standards (DO-367 FLTA, Auto-GCAS) project the path through a response
segment and a climb profile from the airframe's capability and decide
*before* the terrain. Recommended: the same raster lookup and span
stations, run at guidance rate along the projected track, feeding the
existing altitude-setpoint interface, gated by the performance model.

### Measured: the plan versus the run over the control ridge
Planner-chosen altitude 3384 m (peak + 300 m). Minimum span-station
clearance: plan 297.7 m; run with the lee-rotor provider, four seeds,
297.7 m each — **0.0 m difference, because the rotor delivered no
turbulence at all** (total vertical-wind σ identical to three decimals).
Cause: the W20 coupling is inert above 300 m AGL by construction and the
planner's margin is exactly 300 m; the claimed POE index-1 floor above
the ceiling is zero at ~3000 m MSL in JSBSim's MIL-F-8785C table (σ_w
1.12 fps at 500 m AGL over terrain 0; 0.00 fps at 500 m AGL over terrain
2500 m). The turbulence-omission concern is therefore immaterial as
posed; the material finding is that a seeded, provenance-recorded,
conditions-strip-advertised coupling is inert in its own regime — the
class of failure (`§1.6`, "advertised and never delivered") this project
was built to prevent. Ledger 3.4.

## 13. Numerical integration

Fixed 120 Hz from the spec; render FPS separate; guidance divisor scales
with rate; JSBSim default integrators (AB2/AB3 translational, Euler
rotational); ECI propagation; quaternion normalised. Convergence ratio
≈3× per halving of dt. **Stable and frame-rate-independent. No work.**

## 14. Research ledger

`flight-dynamics-research-ledger.md` — 4 cycles, 9 topics, sources
per topic. Blocked from this environment: NTRS, EASA, DLR, arXiv,
Semantic Scholar, SKYbrary, Wikipedia; JSBSim and ArduPilot sources on
GitHub were reachable and are quoted.

## 15. Comparison with mature systems

| concept | JSBSim / ArduPilot / standards | this repository | verdict |
|---|---|---|---|
| propagated state, 6-DOF, quaternion | JSBSim FGPropagate | uses JSBSim unchanged | adopt as-is ✓ |
| control laws at integrator rate | JSBSim FCS `<system>` | tecs.xml derived per airframe, hash-recorded | ✓ |
| TECS normalisation | ArduPilot K_thr2STE from measured climb/sink | fixed gain | adopt |
| turn coordination | β/a_y → rudder or g·sinφ/V feedforward | damper only | adopt |
| trim in wind | JSBSim IC wind (ground-speed-holding) — treacherous | property write clobbered by trim | fixed point on observed (vc, β) |
| path following | L1 (Park–Deyst–How), bank demand | none | adopt only if routes wanted |
| terrain look-ahead | DO-367 sensor profile; Auto-GCAS escape projection | none in flight | adopt, on the existing setpoint interface |
| turbulence | MIL-F-8785C Dryden in the FDM | same | ✓ |

## 16. Ranked airborne failures

Ten, listed in the executive answer with severity and evidence. The brief
asks for twenty-five; there are not twenty-five, and inventing fifteen
would discredit the ten.

## 17. Target architecture

Additive, over the existing pipeline (`mathematical-dependency-map.md` §4):
a performance model measured from the FDM; TECS throttle normalised by it;
a terrain look-ahead consumer feeding the altitude setpoint; a β→rudder
term; trim-in-wind as a fixed point; the controller present on the render
host or a paired asserted headless run; optionally L1 above bank-hold.
Nothing replaces a physics path.

## 18. Mathematical models to introduce

1. **Performance:** Ė_max(m, ρ, V) = (T_max − D)·V/W measured by throttle
   probe at the trimmed state; Ė_min from idle; γ_max = asin(Ė_max/(gV)).
2. **TECS throttle:** δ_thr = Ė_err / (τ (Ė_max − Ė_min)) · (thr_max − thr_min) + ff.
3. **Turn coordination:** δ_r += k_β·β (sign-measured), or δ_r += k·g·sin φ/V.
4. **Trim in wind:** iterate ICs until |vc − vc_cmd| < 0.1 kt and |β| < 0.05°
   with wind present, then trim.
5. **Look-ahead:** for s in [0,T]: z(s) along projected track;
   need = max_s [z(s) + RTC − h_pred(s)]; feasible iff need ≤ ∫Ė_max/g;
   command ḣ ramp, else refuse by name.
6. (optional) **L1:** a_lat = 4ζ²V²/L1·sin η → φ_dem.

## 19. Models not to waste time on

RK4 or any integrator change; a second aerodynamics path; continuous
collision detection; per-mountain gravity; CFD; stratified mountain-wave
solvers (P3, after everything above); waypoint navigation before the
controller reaches the render host.

## 20. P0 → P3 reconstruction roadmap

| step | work | files | proves |
|---|---|---|---|
| 1 (P0) | trim in wind: fixed point on observed (vc, β) in `configure_from_spec`; mirror in `TrimInWind`; guard: post-trim `total-wind` = spec wind or refuse | `runner.py`, `FlightSimScenarioWorld.cpp` | 30 s open-loop excursion < 5 m in 30 kt wind |
| 2 (P0) | delete the first-sample parity exemption once step 1 lands | `test_host_parity.py` | the trim snapshot carries the wind |
| 3 (P0) | pair every render with a closed-loop headless run; assert closure; publish beside the clip | `webapp/runs.py` | closure reaches the artefact |
| 4 (P1) | sign probe at the spec's trimmed state | `signs.py` | c172p engages |
| 5 (P1) | `core/performance.py` (Ė_max, Ė_min, γ_max measured); write to `ap/tecs/stedot-*`; normalise throttle | new, `tecs.xml`, `derive.py` | B747 300 m step < 30 s; same rise time on c172p |
| 6 (P1) | terrain look-ahead consumer on the altitude setpoint, gated by step 5 | new, `runner.py` loop | ridge 60 s ahead → climb; infeasible → named refusal |
| 7 (P1) | make the rotor coupling act where its runs fly: drive severity from the lee field above the ceiling, or lower the ceiling to the measured W20 regime; null test on *delivered* σ_w at the planned altitude, refuse the `lee-rotor` label when zero | `rotor.py`, `test_rotor.py` | delivered σ_w > 0 on a planned mountain track |
| 8 (P2) | β→rudder in `tecs.xml` | `tecs.xml`, `signs.py` | ψ̇ within 2% of g·tanφ/V |
| 9 (P2) | TECS on the render host | ue bridge | delete `project_for_ue_host`'s open-loop projection |
| 10 (P3) | atmosphere provider (ERA5 T, P); stratified orographic option | `environment/` | density altitude changes climb |

## 21. Validation and stress-test plan

Every item is a test that fails when its safeguard is disabled, in the
repository's existing mutation-guard style.

- **Wind trim:** for headwind/tailwind/crosswind 30 kt, post-trim
  `total-wind` equals the spec wind, vc equals the spec airspeed, |β| < 0.1°;
  30 s open-loop altitude excursion < 5 m (today: 333 m).
- **Turn:** at 25° bank, |ψ̇ − g·tanφ/V| < 2% at 230 and 300 kt; |β| < 0.2°.
- **Energy:** 300 m step captures 90% in < 30 s on B747 *and* c172p; TAS
  held within 1 kt; overshoot < 5%; fraction of excess power used > 0.8.
- **Sign probe:** `Autopilot.engage()` succeeds on every configured airframe.
- **Look-ahead:** synthetic ridge 60 s ahead triggers a climb setpoint
  ≥ 30 s before arrival; an unclearable ridge refuses by name; guard:
  horizon set to zero must fail.
- **Rotor delivery:** on a planner-produced mountain track, measured σ_w
  from `atmosphere/total-wind-down-fps` ≥ 0.5 m/s wherever the run is
  labelled `lee-rotor`; today it is 0.000.
- **Plan vs run:** across 8 seeds the run's minimum clearance ≥ plan
  minimum − 5 m once the rotor actually acts.
- **Timestep:** 60/120/240 Hz final positions within 0.5 m (today 0.12).
- **Render parity of control:** the paired headless closure report is
  attached to every rendered run; a deliberately unachievable command
  fails the pair.

## Appendix — experiment scripts

Scratchpad scripts `turn_climb.py`, `beta_ps_rate.py`, `wind2.py`…
`wind7.py`, `c172trim.py`, `c172bisect.py`, `c172step.py`,
`terrain_gap.py`. Each builds the aircraft through `core.fdm.FlightDynamics`
(or `configure_from_spec`), engages `core.control.autopilot.Autopilot`
where closed loop, and reads JSBSim properties directly. Reproduce by
copying any script into the repository root.
