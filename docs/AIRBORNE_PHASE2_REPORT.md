# Airborne physics reconstruction, phase 2 — report

Eight packages (A–H) from `analysis/PROMPT_airborne_reconstruction.md`,
built on the findings of `analysis/flight-dynamics-research-ledger.md`
(finding numbers below refer to that ledger). Every number in this report
is reproduced by a committed script under `experiments/airborne/`; the
command is given with each table. All measurements are on the pinned
JSBSim 1.2.4 build at 120 Hz, mass held, calm air unless the row says
otherwise, run headlessly through the same `run_spec` / `Autopilot` the
web app uses.

The rules the work was held to: `prompt → spec → validate → run`; the
only writer of physical state is `fdm.step()` (nothing here writes
`position/*`, `velocities/*` or `attitude/*`: terrain elevation and wind
are inputs, setpoints are commands); anything a host cannot honour
exactly refuses by name; every gain, limit and condition is measured
from the FDM at the spec's own state, never a constant chosen to suit
one airframe; every new safeguard carries a mutation guard verified to
fail when the safeguard is disabled.

## Before / after

| package | measurement | before | after | script (`experiments/airborne/`) |
|---|---|---|---|---|
| A trim in wind | B747 3000 m / 250 kt, 30 kt head / tail / cross wind: 30 s open-loop altitude excursion | +333 / −327 / — m | 0.78 / 1.14 / 0.96 m | `trim_in_wind_prototype.py` |
| A | c172p 600 m / 85 kt, 20 kt head / cross | — | 0.01 / 0.01 m | same |
| A | fixed-point iterations to hold the spec's vc with β = 0 in the wind | (trimmed in calm air) | 1 | same |
| A | crab angle emerging from the crosswind trim | 0° | ≈ −7° (B747), measured, not commanded | same |
| B sign probe | c172p closed-loop engage | refused (probe at 6000 m / 280 kt cannot trim) | engages at its own state and flies a step | `tests/test_control_signs.py` |
| B | p51d (cannot trim airborne on this build) | bare trim failure inside `engage()` | `control.signs` refusal by name | same |
| C closure | closure report on the rendered artefact | never ran on a render | `capture/closure.json` on every run; a missed closure fails the run by name | `tests/test_closure_pair.py` |
| D performance | B747 300 m altitude step at 3000 m / 250 kt: time to 90 % | 72.7 s | 28.7 s | `tecs_step.py --step 300 [--pre]` |
| D | peak climb rate / controller cap | 4.3 / 12.2 m/s | 12.4 / 12.2 m/s | same |
| D | overshoot / CAS excursion | 0 / — | 0 / 1.0 kt | same |
| D | B747 100 m step, time to 90 % | 23.9 s | 14.5 s | `tecs_step.py --step 100` |
| D | c172p 100 m step at 600 m / 85 kt: time to 90 % / fraction of excess thrust used | 26.9 s / — | 26.0 s / 0.95 | `tecs_step.py --aircraft c172p --step 100` |
| E look-ahead | B747 3000 m / 250 kt at a 3300 m ridge 8 km ahead | left-wingtip impact at 52.6 s | setpoint raised at t = 0 with 54 s lead; 44.8 m minimum AGL at the raster crest; closure passes at 3323 m | `terrain_lookahead.py [--pre]` |
| E | 5000 m crest, same track | impact | `terrain.lookahead` refusal at t = 0: 12.8 m/s required vs 12.2 m/s available | `terrain_lookahead.py --crest 5000` |
| F rotor | σ_w claimed above 300 m AGL | constant 0.544 m/s | measured at the MSL over a 30 s seeded sample (Linux): 0.31 m/s at 450 m, 0.44 at 1000 m, 0.10 at 2000 m, 0.000 at ≥ 3000 m (the zero is exact on every platform; the nonzero values follow the platform C library’s generator) | `rotor_delivery.py` |
| F | delivered σ_w on a planned mountain track (3384 m MSL / 384 m AGL, 35 m/s across the ridge) | 0.000 m/s, labelled `lee-rotor` | 0.000 m/s, labelled "lee-rotor turbulence absent: …" with the reason | same |
| F | delivered σ_w in the lee at 150 m AGL, 35 m/s (25 m/s) | not measured | 0.357 (0.256) m/s; `lee-rotor` at 35 m/s, "absent" at 25 | same |
| G coordination | B747 25° bank at 230 / 300 kt: turn-rate error vs g tan φ / V | −10.3 % / −11.5 % | −1.1 % / −0.8 % | `turn_coordination.py [--pre]` |
| G | sideslip β in the turn (peak) | 1.16° / 0.82° | −0.005° / −0.002° (0.09° / 0.03°) | same |
| G | side force Y/W in the turn | −0.039 / −0.046 | 0.00015 / 0.00009 | same |
| G | heading rise time, 10–90 % of a 90° step | 44.9 / 59.2 s | 41.1 / 52.7 s | same |
| G | Dutch roll after a 1 s rudder pulse at 230 kt: settle to 0.05° / peak β / ζ / period | 7.7 s / 0.29° / 0.43 / 9.4 s | 5.0 s / 0.18° / 0.25 / 5.1 s | same |

Suite: 583 tests and 118 mutation guards before the reconstruction;
635 tests (plus 1 skipped) and 131 guards after, every new guard verified to fail
its test when the safeguard is disabled (`scripts/mutation_check.sh`).

## A — The aircraft is trimmed in the spec's wind (findings 4, 5)

**Root cause, measured.** `FGTrim::DoTrim` calls `Initialize(&fgic)`,
which re-applies the initial-condition wind (zero) over any
`atmosphere/wind-*` written before trim. Both hosts therefore trimmed in
calm air and received the spec's wind as a step on step one: +333 m and
−327 m of altitude in 30 s open loop for a 30 kt head and tail wind on
the B747.

**Fix.** `FlightDynamics.set_wind_initial_conditions()` places the wind
in the ICs (`ic/vw-mag-fps`, `ic/vw-dir-deg` — the direction the wind
blows *toward* — and the NED ground-velocity ICs) and iterates a fixed
point on the *observed* `velocities/vc-kts` and `aero/beta-deg`, because
JSBSim's IC route holds ground speed and re-derives airspeed. The guess
v_ground = v_air (along the heading) + v_wind converges in one iteration
on every case measured; a fixed point that does not converge raises
`TrimStateError` (`wind.trim_state`). `verify_wind_state()` then checks
the trimmed state carries the wind at the spec's airspeed with no
sideslip, or the run refuses by name — the runner, both web-app
pre-flights and the UE host all go through it. The parity harness no
longer exempts the first sample: the trim snapshot is graded and must
carry the wind.

**Engine host (C++, additive, not compiled here).**
`FFlightSimScenarioWorld::TrimInWind` in
`ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp`
mirrors the Python: the wind goes into the same ICs, `do_simple_trim`
runs, and the total wind / vc / β are verified to the same tolerances,
else the card is refused with `wind.trim_state`. To verify on a machine
with the engine: build the plugin, render any windy card, and confirm
the render log carries no `wind.trim_state` line and the first telemetry
sample's `wind_speed_mps` equals the card's; then run
`experiments/gate5_ue_parity.py` against the headless run of the same
card — the first sample is now graded.

## B — The sign probe flies the aircraft's own state (finding 7)

`Autopilot.engage()` passes the engaging aircraft's trimmed altitude and
CAS to `core.control.signs.measure`, which used to probe at a hardcoded
6000 m / 280 kt; a probe that cannot trim raises `ControlSignError`
(`control.signs`) naming the condition. The c172p now engages and flies
closed loop; the p51d, which cannot trim at any airborne condition on
this build (JSBSim reports the u-dot channel untrimmable), refuses by
name instead of failing inside the autopilot.

## C — The closure assertion reaches the rendered artefact

The render host has no controller, so every clip is open loop and the
closure assertion never ran on the thing a person looks at. Every run
now flies the SAME spec closed loop headlessly (`webapp/capture.py:
closure_run`), writes `capture/closure.json` beside the clip (four
checks: altitude, airspeed, heading, settled), and FAILS the run by name
(`closure.<check>`) when the commanded state was not reached. The page
renders the report; a run without a controller reports
`closure.unavailable`.

## D — A measured performance model, and a throttle loop that knows it (finding 2)

**Root cause, measured.** The TECS throttle gains were dimensionless
constants: `ste-error` is the required thrust-to-weight change, so the
right throttle command per unit of it is the airframe's own
Δthrottle / Δ(T/W), which is 1.1 on the B747 and very different on the
c172p. With one constant the B747 used 54 % of its excess power in a
climb.

**Fix.** `core/performance.py` measures, on a throwaway instance at the
engaging state: trim thrust (= drag in level flight), full and idle
thrust after a spool, and a local throttle-thrust secant (±0.15) — from
which Ė_max = (T_max − T_trim)·V/W, Ė_min, γ_max and `thr_per_ste`. At
engage the throttle P and I gains are multiplied by the measured
`thr_per_ste` (the ArduPilot `K_thr2STE` / Lambregts T/W scaling), a
feed-forward on the demanded energy rate is added, and the climb-rate
limit is capped at 80 % of the measured Ė_max. A probe that finds no
excess power refuses (`performance.measure`). The energy-distribution
gain was then swept (0.5 / 1.0 / 1.5 / 2.0 → 43.9 / 33.7 / 30.4 / 28.7 s
to 90 % on the 300 m step) and 2.0 adopted.

**What physics does not allow.** The brief asked for the c172p to fly a
300 m step in under 30 s and for rise times within 20 % across
airframes; at 600 m / 85 kt the c172p's measured Ė_max is 7.2 m/s and it
is throttle-saturated, so the tests assert what the model supports: the
c172p tracks with 95 % of its excess thrust in use.

## E — Terrain look-ahead on the altitude setpoint (finding 8)

`core/terrain/lookahead.py` samples the baked raster along the projected
ground track (the current inertial velocity held — there is no
navigation this phase) out to 90 s at half the raster pitch, at the
airframe's span stations. Terrain + RTC (`MIN_CLEARANCE_M`, the
validator's own floor) above the held altitude raises
`ap/altitude-setpoint-ft` through the autopilot's command surface, only
ever upward, one hold-tolerance band above the requirement so a hold at
the bottom of its band still carries the RTC. An escape profile (the
present climb rate for the controller's response time, then the
controller's climb limit from package D) that cannot clear a sample
refuses the run as `terrain.lookahead` before the impact, naming
distance, required and available climb. Raises are telemetry events and
manifest provenance; the web capture carries `terrain.lookahead` and
`terrain.impact` to the page by name.

## F — The rotor acts, or says by name that it does not (finding 9)

**Root cause, measured.** The rotor coupling delivers through W20, which
the pinned build honours below 300 m AGL only; the planner keeps every
mountain track ≥ 300 m above the terrain; and above the ceiling the POE
severity-1 curve is indexed by MSL and is zero at ~3000 m. So every
planner-produced mountain run said `lee-rotor` on its card, its
conditions strip and its provenance while the FDM delivered 0.000 m/s.

**Fix (the brief's option ii, with measurement).** The claimed σ_w above
the ceiling is measured at the planned MSL from a throwaway FDM
(`measure_poe_sigma_w_mps`) instead of read from the 1000 m ladder
constant. The provider observes `atmosphere/turb-down-fps` every step
through a read-only `observe()` hook on the stack and `acts()` only if
the delivered RMS reaches 0.3 m/s. The web app pre-flies the card's own
track with the rotor attached; a rotor that did not act is dropped from
the card, and the strip states why with the delivered value. The
orographic lift/sink (a mean wind) still travels and is still reported.

The brief named `atmosphere/total-wind-down-fps` for the delivered
value; that channel carries the orographic sink (measured σ = 1.15 m/s
with zero turbulence), so the Dryden component `atmosphere/turb-down-fps`
is used and the report says so.

## G — Turn coordination (finding 1)

The yaw channel was a washed-out yaw-rate damper alone. `core/control/
coordination.py` measures, at the engaging state, the steady sideslip a
rudder offset produces with wings held level (12.3° per unit rudder on
the B747 at 230 kt) and sets the sideslip-to-rudder proportional gain to
close the loop at gain 2 with the measured sign, plus an integral term
(4 s). The loop gain was swept (2 / 3 / 5: identical coordination,
Dutch-roll damping ratio 0.21 / 0.19 / 0.14 with the damper at 1.5 and
0.25 / 0.22 / 0.18 at 3.0); 2 with the damper raised to 3.0 keeps the
mode at MIL-F-8785C Level 1. The Dutch roll after a rudder pulse now
settles faster with a smaller peak; its damping *ratio* is lower because
the mode is stiffer (period 9.4 s → 5.1 s), which the report states
rather than hides.

## What was not done, and why

* **Package D on the c172p** cannot meet the brief's 30 s / 20 % numbers
  (physics; above).
* **Porting TECS to the engine host, waypoint/L1 navigation, takeoff and
  landing, integrator changes, a second aero path, CCD, atmosphere T/P,
  stratified waves** are out of scope by the brief.
* **The C++ `TrimInWind`** is additive and compile-safe by inspection but
  was not compiled or rendered here (no engine in this environment); the
  verification steps are in package A.
* **Rotor turbulence on a planned track** still does not act: the planner
  keeps tracks above the ceiling and the pinned build's W20 route is
  inert there. The run now says so instead of claiming it.

## Fixed on the way

* "over 2000 m mountains" compiled to a 2000-minute duration (a bare "m"
  after "over" read as minutes), which the capture phase then flew in
  full. The bare "m" is minutes only after "for"/"during".
* The closure-pair and capture tests pin the flat scene, so a baked
  control ridge no longer turns the 5000 ft prairie prompt into a
  `terrain.clearance` refusal; the render-flow tests hold the mesh gate
  open on a machine without the engine.
