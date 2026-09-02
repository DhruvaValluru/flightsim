# Airborne Physics Reconstruction — implementation brief

Paste everything below this line into a fresh session as the task. It is
self-contained: it tells the session what was found, where the evidence
is, what to build, in what order, and how "done" is measured.

---

# TASK: Airborne Physics Reconstruction, packages A–H

## Context you must read first

The repository `DhruvaValluru/flightsim` is a JSBSim-based scenario
harness (prompt → provenanced spec → validate → run) with two hosts
(headless Python runner and an Unreal commandlet) sharing one physics
core and one card. An audit (commit `195641e`, branch
`claude/flightsim-windows-deploy-oxzf2o`) flew the aircraft headlessly
over four cycles and wrote:

* `analysis/flight-dynamics-audit.md` — findings, roadmap, tests
* `analysis/flight-dynamics-research-ledger.md` — every measurement,
  every source, cycle by cycle
* `analysis/mathematical-dependency-map.md` — every coupling, intact
  and severed

Read all three before touching code. Then read `docs/VALIDITY.md`,
`NEXT.md`, `core/scenario/runner.py`, `core/control/autopilot.py`,
`core/control/systems/tecs.xml`, `core/control/signs.py`,
`core/environment/rotor.py`, `webapp/runs.py` (planners and
`_render_flow`), `tests/test_host_parity.py`, and
`ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp`
(`TrimInWind`).

**The verdict that frames the work:** the dynamics are correct and must
not be touched — JSBSim 6-DOF, one writer of state, zero fake physics,
frame-rate independent to 12 cm / 22 s. Every defect is at a boundary:
initialisation, a control-law gain, a missing model, a dead coupling, a
host asymmetry. You are fixing boundaries, not physics.

## The findings you are fixing (measured; reproduce before you change anything)

| # | finding | measured | proof of fix (already measured) |
|---|---|---|---|
| 1 | **Neither host trims in the wind.** `FGTrim::DoTrim` calls `Initialize(&fgic)` which re-applies zero wind ICs over the `atmosphere/wind-*` property writes. Every windy run starts with a wind step from a calm trim. | wind −50.6 fps before `trim()`, 0.00 after; open loop 30 s: headwind +333 m, tailwind −327 m; TECS 60 s: 44 m balloon, 39 m band | trimmed in wind: 1.4 m / 0.6 m open loop, 0.02 m closed loop |
| 2 | `tests/test_host_parity.py:109` exempts the first sample (288 vs 301 kt) — that sample IS finding 1 | — | delete the exemption after 1 |
| 3 | Render host is open loop (`project_for_ue_host` sets `hold_state=False`); closure never runs on a clip | — | paired headless run |
| 4 | Sign probe hardcoded at 6000 m / 280 kt (`signs.measure`); c172p cannot engage | `TrimFailureError` inside `engage()` at 3 flyable conditions | probe at 600 m/85 kt → engages, flies a step |
| 5 | TECS throttle gain not normalised by airframe performance (`kt-p` 1.2 on Ė/(gV)) | B747 uses 17–54% of excess power; c172p saturates at 98% throttle; 300 m step takes 75 s | normalise by measured (Ė_max − Ė_min) |
| 6 | No in-flight terrain look-ahead; terrain's only action is `TerrainImpactError` | — | needs 5's performance object |
| 7 | Lee-rotor turbulence delivers ZERO on planner tracks: W20 route inert ≥300 m AGL, planner margin = 300 m, POE-1 floor is 0 at ~3000 m MSL; `expected_sigma_w_mps` claims 0.54 m/s there | 4 seeds, 0.0 m clearance change, σ_w identical to 3 dp | deliver it or label it |
| 8 | Turns uncoordinated: yaw damper only, no β feedback | β 1.08°, ψ̇ 9% under g·tanφ/V, explained to 1.3% by side force | β→rudder term |

## Hard rules (unchanged from the camera phase, plus two)

1. `prompt -> spec -> validate -> run`, never `prompt -> run`.
2. **Never write into `position/*`, `velocities/*`, `attitude/*`.** The
   only writer of physical state is `fdm.step()`. Terrain elevation and
   wind are inputs; setpoints are commands. If a fix needs to move the
   aircraft, it is the wrong fix.
3. Anything a host cannot honour exactly it refuses by name; nothing is
   approximated silently. New refusals get a constraint name.
4. Determinism: no wall-clock, no RNG outside seeded subsystems, no
   frame-rate dependence.
5. **Measure, don't assume.** Every gain, limit or condition you add is
   derived from the FDM at the spec's own state (the
   `envelope.measure_lift_curve` / `signs.measure` pattern), never a
   constant that happens to suit one airframe.
6. Do not weaken, skip or delete any existing test or guard except the
   one parity exemption named in package A, and only after A's guard
   proves it unnecessary. The suite (583 tests, 118 mutation guards
   in `scripts/mutation_check.sh`) must only grow. Every new safeguard
   gets a guard verified to fail when the safeguard is disabled.
7. C++ changes are additive and compile-safe, gated behind
   `core/util/platform.ue_available()`; you cannot compile them here —
   say so in the report and leave exact macOS/Windows verification steps.
8. Work in packages. Each = code + tests + guards + one commit, suite
   green after each. Do not start the next package on a red suite.
9. Every claim in your final report carries a measurement you made in
   this session, reproduced from a script you committed under
   `experiments/airborne/`.

## Packages, in dependency order

### A — Trim in the wind (P0)
**Where:** `core/scenario/runner.py:configure_from_spec`; mirror in
`FlightSimScenarioWorld.cpp:TrimInWind` (additive, unverified here).
**What:** after `set_initial_conditions`, `start_engines`: write the
wind, then iterate — `run_ic`, read `velocities/vc-kts` and
`aero/beta-deg`, adjust the ground-speed and heading ICs by the
discrepancy — until |vc − spec| < 0.1 kt and |β| < 0.05°, then `trim`.
Do NOT rely on `ic/vw-*` semantics alone: measured, `ic/vw-dir-deg` is
the direction the wind blows *toward*, the IC route holds ground speed
(250 kt commanded came out 303/197 kt), and a naive crosswind IC trims
into a 29°-banked, 12°-slip state. The fixed point on the *observed*
air-relative state is the robust route. Record the iteration count in
the manifest.
**Guard:** after trim in a wind spec, `atmosphere/total-wind-{n,e}` must
equal the spec wind and `vc` the spec airspeed, or refuse
`wind.trim_state` by name.
**Tests:** for headwind/tailwind/crosswind 30 kt on B747 and c172p:
post-trim wind, vc, |β| as above; 30 s open-loop altitude excursion
< 5 m (today 333 m); crab emerges at trim (crosswind: heading ≠ track).
Then delete the first-sample exemption in `test_host_parity.py` and
make that test assert the trim snapshot carries the wind.
**Done when:** the ledger's Cycle 2 "today" column reproduces on the
pre-change tree and the "trimmed in wind" column on the post-change tree.

### B — Sign probe at a reachable state (P1)
**Where:** `core/control/signs.py:measure`; `autopilot.engage`.
**What:** probe at the spec's own trimmed condition (pass altitude and
CAS from the engaging FDM), or at `envelope.reference_speeds` cruise.
Keep the cache keyed by airframe (the convention is condition-independent
— measured on c172p: +elevator nose down, +aileron roll right, +rudder
yaw left).
**Guard:** `engage()` on every airframe in `assets/aircraft_config`
succeeds, or refuses `control.signs` naming the condition tried.
**Tests:** c172p engages at 600 m/85 kt and flies a 100 m step.

### C — Closure reaches the rendered artefact (P0)
**Where:** `webapp/runs.py:_render_flow`, `webapp/capture.py`.
**What:** for every render, run the same spec headlessly with
`hold_state=True` (the capture run already exists — extend it), assert
`ClosureReport`, write `closure.json` beside the clip, surface it in the
run panel and `/runs/{id}/files`. A failed closure is a named failure of
the run, not a note.
**Guard:** a deliberately unachievable command fails the paired run.
**Tests:** the closure report is present and `ok` for a level-flight
render; absent → run status `failed` with `closure.*`.

### D — Performance model + TECS normalisation (P1)
**Where:** new `core/performance.py`; `core/control/derive.py`;
`core/control/systems/tecs.xml`; `autopilot.engage`.
**What:** `measure_performance(fdm)` at the trimmed state: Ė_max =
(T_max − D)·V/W by full-throttle probe on a copy, Ė_min from idle,
γ_max = asin(Ė_max/(gV)). Write `ap/tecs/stedot-max`, `stedot-min` at
engage. In `tecs.xml`, replace the fixed `kt-p` path with
δ_thr = Ė_err / (τ·(Ė_max − Ė_min)) · (thr_max − thr_min) + feedforward
(ArduPilot `AP_TECS.cpp` `K_thr2STE`; Lambregts T/W scaling). Keep
anti-windup and the pitch path as they are — they are right.
**Guard:** `ap/tecs/stedot-max` is written from a measurement, never a
constant; a mutation that hardcodes it must fail.
**Tests:** 300 m step: 90% capture < 30 s on B747 (today 75 s) and on
c172p; TAS held within 1 kt; overshoot < 5%; fraction of excess power
used > 0.8 on both; the two airframes' rise times within 20% of each
other.

### E — Terrain look-ahead on the altitude setpoint (P1)
**Where:** new `core/terrain/lookahead.py`; hooked in
`runner.run_spec`'s loop at guidance rate (every 60 steps); optional in
the render card as a pre-computed setpoint schedule.
**What:** sample the raster along the projected ground track for
T = 90 s (use `Heightfield.elevation_at` and the span stations from
`core/terrain/contact.py`); required Ė = g·(z_ahead + RTC − h)/t_ahead
with RTC = `MIN_CLEARANCE_M` (30 m) en route; ask package D for Ė_max;
feasible → ramp `ap/altitude-setpoint-ft` (rate-limited by
`hdot-max`); infeasible → refuse `terrain.lookahead` by name with the
distance, the required and available climb. Structure it as the DO-367
FLTA sensor profile: a response segment at the current velocity vector,
then a climb at γ_max. No lateral avoidance in this phase.
**Guard:** horizon set to zero must fail the tests.
**Tests:** synthetic ridge 60 s ahead (the `make_mountain` fixture
pattern) → climb setpoint issued ≥ 30 s before arrival and the run
clears it; an unclearable ridge → named refusal before impact; a flat
scene → setpoint never moves.

### F — The rotor either acts or says it doesn't (P1)
**Where:** `core/environment/rotor.py`; `tests/test_rotor.py`;
`webapp/runs.py` conditions strip.
**What:** either (i) above `LOW_ALTITUDE_CEILING_M` drive the MIL-F-8785C
*severity* index from the lee-sink field at configure time (JSBSim
accepts a constant severity), so the coupling delivers σ_w where planned
tracks fly, or (ii) keep the model and change `card_word`, provenance and
the conditions strip to state that rotor turbulence acts only below
300 m AGL and is absent on this track. Replace `expected_sigma_w_mps`'s
constant "floor" with a value measured from the FDM at the planned MSL.
**Guard:** a run may carry the word `lee-rotor` only if delivered σ_w
(from `atmosphere/total-wind-down-fps`) ≥ 0.3 m/s over the run.
**Tests:** on the control ridge at the planner's altitude, delivered
σ_w > 0 (today 0.000) under (i), or the label is absent under (ii).

### G — Turn coordination (P2)
**Where:** `core/control/systems/tecs.xml` yaw channel; `signs.py`.
**What:** add δ_r += k_β·β (sign-measured) or δ_r += k·g·sinφ/V
feedforward alongside the existing washout damper.
**Tests:** at 25° bank, 230 and 300 kt: |ψ̇ − g·tanφ/V| < 2% (today
9%), |β| < 0.2° (today 1.08°), Dutch-roll damping not degraded (the
existing response characterisation).

### H — Report
`docs/AIRBORNE_PHASE2_REPORT.md`: per package, the pre-change and
post-change measurement side by side, the scripts under
`experiments/airborne/`, the C++ left unverified with exact steps,
and the updated counts (tests, guards). Update `NEXT.md` and `README.md`.

## Out of scope
Waypoint/route navigation and L1 guidance; takeoff, landing, ground
phases; any integrator change; a second aerodynamics path; continuous
collision detection; atmosphere T/P deviations; stratified mountain-wave
solvers; porting TECS into the engine host (note it as the follow-on to
package C).

## Definition of done
All eight packages committed on the designated branch with a green
suite after each; every new safeguard has a verified mutation guard;
the report's tables reproduce from committed scripts; PR opened as a
draft with the pre/post table in its body. If a package is blocked (an
engine you cannot run, a JSBSim behaviour you cannot make consistent),
finish every other package, state precisely what blocked it and what
you measured, and do not scale the package down silently.
