# Corrections to the §6 reference, measured against JSBSim 1.2.4

Pinned build: `1.2.4 [GitHub build 1671/commit e07a7d81] Feb 7 2026`, Python
bindings, macOS, Python 3.9.6.

The brief flagged several §6 items `[VERIFY]`. Verifying them turned up four
things that are not merely uncertain but **wrong in a way that silently produces
a bad run** — the failure mode of §1.6, where the system advertises a condition
it does not have. Each is recorded here with the measurement, because each one
would otherwise be rediscovered the hard way.

---

## 1. `ic/vw-north-fps` / `-east-fps` / `-down-fps` are READ-ONLY

§6.1 lists these among the settable initial conditions. They are not.

```
ic/vw-north-fps   (R)
ic/vw-east-fps    (R)
ic/vw-down-fps    (R)
ic/vw-mag-fps     (RW)   <- the writable route
ic/vw-dir-deg     (RW)
```

JSBSim ignores writes to read-only properties **with no diagnostic**, so setting
an initial wind the obvious way appears to succeed and does nothing. Initial
wind must be specified as magnitude and direction.

Guarded by: `PropertyAccess.set` raises `ReadOnlyPropertyError`.
Test: `tests/test_properties.py::test_ic_wind_ned_components_are_read_only`.

---

## 2. Initial conditions silently overwrite each other

**The most dangerous finding**, and there are two instances of it. Initial
conditions are order-dependent, JSBSim applies them in the order written, and a
clobbered field is reported nowhere.

### 2a. `ic/lat-geod-deg` overwrites `ic/vc-kts`

Setting geodetic latitude *after* an airspeed re-derives the velocity state and
reinterprets the already-converted true airspeed as calibrated, applying the
density conversion twice.

Requested 250 kt CAS, with `ic/lat-geod-deg` set afterwards:

| Altitude | Requested CAS | Achieved CAS | Achieved Mach |
|---:|---:|---:|---:|
| 0 m | 250 | 250 | 0.378 |
| 3000 m | 250 | **288** | 0.518 |
| 6000 m | 280 | **373** | 0.794 |
| 10000 m | 300 | **486** | **1.281** |

At 10 km the requested transport cruise point became **supersonic**. Trim then
fails, and the failure looks like a solver problem rather than a bad initial
condition. Only geodetic latitude does this — `ic/long-gc-deg` does not.

### 2b. `ic/beta-deg` overwrites `ic/psi-true-deg`

Found later, by the verification below rather than by inspection. Setting
sideslip re-derives the velocity vector's orientation and resets true heading to
zero: a requested heading of 270 becomes 000, silently. Only sideslip does this
— `phi`, `gamma`, `alpha` and `vc` all leave heading alone.

### The guard

Two independent mechanisms, because ordering alone rots the moment a new IC key
is added — and 2b is exactly that, discovered *after* the ordering fix for 2a
was already in place:

1. `_IC_PRIORITY` in `core/fdm/fdm.py` fixes a safe order: position, then
   attitude with **sideslip strictly before heading**, then flight-path terms,
   then speed last so nothing can re-derive it.
2. `_verify_initial_conditions` compares every requested condition against the
   state actually achieved and raises on a mismatch. This is what caught 2b.

The order is verified *as a whole* rather than reasoned about:
`test_every_initial_condition_is_achieved_simultaneously` sets nine fields to
distinct non-default values and asserts all nine are achieved at once. Both
alternative orderings that seem equally reasonable — heading before sideslip,
and speed first — fail it.

Tests: `tests/test_initial_conditions.py`.

---

## 3. The property tree silently creates nodes on write

Not flagged in the brief at all, and the lowest-level instance of §1.6.

```python
>>> fdm.set_property_value("totally/made/up/property", 42.0)
>>> fdm.get_property_value("totally/made/up/property")
42.0
>>> fdm.get_property_value("never/written/at/all")
0.0
```

A misspelled property **writes successfully, reads back the value you wrote, and
has no effect on the simulation.** A misspelled read returns a plausible zero.
Mistype `atmosphere/wind-north-fps` and you get a run that reports wind and does
not have any — exactly the previous build's unverifiable `WIND 270/25KT`.

Guarded by: all access routed through `PropertyAccess`, which resolves names
against the loaded model's catalog.

Catalog quirk: index 0 is stored **without** a subscript. The catalog contains
`fcs/throttle-cmd-norm` and `fcs/throttle-cmd-norm[1]` but never
`fcs/throttle-cmd-norm[0]` — though that name does alias correctly. `[0]`
suffixes are stripped before lookup rather than rejected. Same for
`gear/unit[0]/...`. §6.1's `fcs/throttle-cmd-norm[N]` and
`gear/unit[N]/wheel-speed-fps` are therefore wrong for N=0 as catalog keys,
right as accessors.

---

## 4. Engine state is not observable from thrust

Not in the brief; found while diagnosing the first Gate 0 run.

JSBSim aircraft load with engines **stopped**. Trim then solves for a throttle
that can produce no thrust, logs `Sorry, udot doesn't appear to be trimmable`,
and — if it converges anyway — returns a plausible-looking alpha and throttle
attached to an unpowered glider. The first Gate 0 run trimmed "successfully" at
3000 m and then descended at 30 m/s.

Thrust cannot be used to verify the fix, because a turbofan at zero throttle
produces essentially nothing either way:

| | N1 | Thrust @ 3000 m | Thrust @ 6000 m |
|---|---:|---:|---:|
| stopped | 0% | 12 lbf | 0 lbf |
| running, throttle 0 | 30% | 12 lbf | 0 lbf |

`propulsion/engine[N]/running` **does not exist**. Verification is by spool
state: `propulsion/engine[N]/n1` goes 0 → 30% on start.

Guarded by: `FlightDynamics.start_engines()` checks N1; `trim()` refuses an
airborne trim with engines stopped.

---

## 5. Smaller confirmations and gaps

* **`do_trim` mode integers confirmed** from the binding's own docstring:
  `tLongitudinal=0, tFull=1, tGround=2, tPullup=3, tCustom=4, tTurn=5, tNone=6`.
* **`jsbsim.TrimFailureError` exists** and `do_trim` raises it. The exported
  exceptions are exactly `BaseError`, `GeographicError`, `TrimFailureError`.
* **`SetGammaFallback` is NOT exposed** in the Python bindings. §5 Phase 0
  suggests it as a trim-failure retry; that path is unavailable headless. The
  only retry is relaxing the initial condition, which the caller does explicitly.
* **`SetProbabilityOfExceedence` is NOT exposed** either. The POE路 must be
  driven through `atmosphere/turbulence/milspec/severity`. The 0-7 mapping in
  §6.2 remains **unverified** and must be checked before Phase 3 relies on it.
* **Turbulence type enum is not exported** to Python (`ttMilspec` etc. are
  absent). `atmosphere/turb-type` must be set as a bare number, so the
  `{ttNone=0 … ttTustin=4}` mapping in §6.2 is still **unverified** — a Phase 3
  null test must confirm it rather than assume it.
* **All other §6.1 / §6.2 property names verified present** on `global5000`:
  accelerations, position, attitude, velocities, aero, fcs commands and
  positions, atmosphere, wind, turbulence, gust, mass, and ICs — 76 of 77
  checked names, the exception being the `[0]` subscript artifact above.
* **`gear/unit/wheel-speed-fps` confirmed** (the §6.1 `[VERIFY]` item), with the
  index-0 caveat.

---

## 6. Lift is `+forces/fwz-aero-lbs`, and the sign is silent

Wind-frame Z carries lift with a positive sign on the pinned build. Getting it
backwards does not raise: an inverted lift curve still yields a CLmax and a
stall speed, just at the wrong end of the alpha sweep. Measured on the B747, the
inverted form reported CLmax 0.104 at the sweep minimum and a stall speed of
**526 kt**; the correct form gives CLmax 1.192 at 13.5 deg and Vs 155 kt.

The guard is the `clipped` flag on `LiftCurve`: a CLmax landing on a sweep edge
means the stall was never bracketed, which is true both of an inverted curve and
of a sweep that simply did not reach far enough.

Measured lift curves, clean configuration:

| Model | CLmax | alpha at CLmax | Vs at reference mass, sea level |
|---|---:|---:|---|
| B747 | 1.192 | 13.5 deg | 155 kt @ 250,000 kg |
| 737 | 1.182 | 12.9 deg | 151 kt @ 48,534 kg |
| global5000 | 0.998 | 13.4 deg | 152 kt @ 36,339 kg |

The B747 figure sits inside the published clean 1 g band of roughly 150-165 kt
at that weight. That is a sanity check on the model, **not** a validation of the
aircraft — see docs/VALIDITY.md.

---

## 7. JSBSim imposes no control-sign convention

Each aircraft's own `<flight_control>` decides whether a positive
`fcs/*-cmd-norm` command pitches up or down. Measured on the B747:

| command | +0.05 for 3 s | meaning |
|---|---|---|
| elevator | pitch 2.60 -> 1.05 deg, q −0.32 deg/s | positive = nose **DOWN** |
| aileron | roll 0.00 -> 2.44 deg, p +1.04 deg/s | positive = roll right |
| rudder | r −0.25 deg/s | positive = yaw **LEFT** |

A controller that hardcodes one convention does not fail loudly on an airframe
using the other — it closes the loop with positive feedback. The first TECS run
here pitched down through 2676 m and hit NaN in 89 s.

`core/control/signs.py` measures the convention per airframe on a throwaway
instance and writes `ap/sign/*` for the XML to multiply through. A control that
produces no measurable response is an error, not a defaulted +1.

---

## 8. JSBSim FCS channels run whether or not your autopilot is "engaged"

Every `<channel>` is evaluated from the moment the model loads. Gating only the
*output* leaves the PIDs integrating continuously, and while disengaged the
setpoints are zero, so the errors are enormous. Engaging then applies the
accumulated integrator state in a single frame: measured here, elevator
`0.000 -> +0.398` and throttle `0.689 -> 0.539`, costing 33 m of altitude.

JSBSim's `<trigger>` semantics are the fix — **zero runs normally, positive
holds, negative resets to zero** — so the trigger is driven to −1 while
disengaged. Worst engage excursion after the fix: **0.04 m**.

Two related notes on `<system>` XML, both of which cost debugging time:

* **XML comments cannot contain `--`.** Dashed separator rules inside `<!-- -->`
  are a parse error, and JSBSim reports it only as a line number.
* An output switch whose `<default>` reads a *different* property than it writes
  is not a no-op. Defaulting the throttle switch to a separate "passthrough"
  property that was zero before engage silently zeroed all four throttles every
  frame, and the trim solver reported `Sorry, udot doesn't appear to be
  trimmable` on an airframe that trims fine without the controller. The
  disengaged path must write each actuator's *current* command back to it.

---

## 9. Turbulence: the enum, the POE ladder, and a fatal way to drive it

Both §6.2 items flagged `[VERIFY]` are now measured.

**Enum confirmed**: `ttNone=0, ttStandard=1, ttCulp=2, ttMilspec=3, ttTustin=4`
(0 and 5 produce nothing; 3 and 4 are the Dryden pair). Two are unusable:
`ttStandard` produces zero turbulence from milspec parameters, and **`ttCulp`
diverged**, reaching a load factor of 1.5e9 before the run was killed.

**Never re-seed inside the step loop.** `atmosphere/randomseed` seeds a
stochastic process with internal state. Re-writing it every step restarts the
generator each frame and destroys the correlated noise:

| | peak turbulence | peak &#124;Nz−1&#124; |
|---|---:|---:|
| seed written once | 37.6 fps | 0.40 g |
| re-seeded every step | 566 fps | **515 g** |

This does not look like a bug in the output — it looks like violent turbulence.

**Intensity is set two different ways depending on altitude**, and §6.2
describes only one of them. Measured σ_w:

| altitude AGL | W20=15 | W20=30 | W20=60 |
|---|---:|---:|---:|
| 60 m | 1.606 | 3.204 | 6.741 |
| 150 m | 1.634 | 3.269 | 6.543 |
| 300 m | 1.619 | 3.239 | 6.486 |
| 1000 m | 10.876 | 10.876 | 10.876 |

Below roughly 300 m, σ_w ≈ 0.107·W20 — the standard's σ_w = 0.1·W20, reproduced.
Above it **W20 has no effect whatsoever** and the probability-of-exceedence
index governs. A vocabulary built on W20 alone would therefore have produced
turbulence that silently ignored its own intensity setting at altitude.

Measured POE ladder (ttMilspec, 1000 m, σ_w in ft/s):

| index | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| σ_w | 0.000 | 1.785 | 3.603 | 7.729 | 10.953 | 15.905 | 22.240 | 27.168 |

§6.2's suggested mapping (3=light, 4=moderate, 6=severe) does not match the
conventional intensity bands against these numbers. `core/environment/turbulence.py`
instead targets σ_w directly and picks the nearest index, publishing both.

---

## 10. A wind set once at init is NOT overwritten

§5 Phase 3 states that "JSBSim's atmosphere model overwrites wind properties if
you set them once at init". On the pinned build it does not. Measured after 10 s:

| | commanded east | total-wind east |
|---|---:|---:|
| turbulence off, set once | 42.20 fps | 42.20 fps |
| turbulence off, rewritten each step | 42.20 | 42.20 |
| turbulence on, set once | 42.20 | 42.20 |
| turbulence on, rewritten each step | 42.20 | 42.20 |

Writing every step is still required here, but for a different reason: the
providers are functions of position and time, so a boundary-layer profile, an
orographic field or a gust must be re-evaluated as the aircraft moves. A uniform
wind is the single case where it does not matter — which is exactly why testing
only that case would prove nothing.

Note also that `atmosphere/wind-mag-fps` with `atmosphere/psiw-rad` produced the
**opposite sign** to the equivalent NED components, so the NED route is used
throughout.

---

## 11. `attitude/psi-deg` returns 360.0 for north at some positions

The initial-condition check compares each requested value against the state
achieved. For heading that comparison has to wrap: a requested 0 came back as
**360.0** — the same heading — and a plain subtraction reported a 360-degree
error and aborted the run.

It does not reproduce at the equator/prime-meridian origin used by most tests;
it surfaced only once a scenario was placed at a real longitude from a DEM's
centre. Any angular initial condition needs wrap-aware comparison.

---

## 12. Environment hazard: bytecode is cached outside the repo

Not a JSBSim issue, but it corrupted a mutation-test result here and would
corrupt any reproducibility claim, so it is recorded with the rest.

macOS system Python sets `sys.pycache_prefix`:

```
sys.pycache_prefix -> /Users/<user>/Library/Caches/com.apple.python
```

Bytecode therefore lives at `<prefix>/<absolute-path-to-source>.pyc` and **not**
in `__pycache__` inside the tree, so `find . -name __pycache__ -delete` purges
nothing. A mutation that swaps two digits leaves the file size unchanged, and a
restored source was shadowed by stale bytecode compiled from the mutated
version: a correct fix appeared to fail, and the module's own dict disagreed
with its own source text in the same process.

`scripts/mutation_check.sh` purges both locations around every mutation.

---

## 13. Turbulence intensity may move mid-run ONLY via W20, below 300 m AGL

Phase 7's lee-rotor coupling and evolving-conditions schedule both need
turbulence intensity to change while the process runs (seed written once —
§9's re-seed failure stands). Whether the pinned build supports that was
measured before anything depended on it: `experiments/turb_perstep_measure.py`,
report in `runs/turb_perstep/report.json`.

**Re-writing severity/W20 every step with unchanged values is an exact
no-op** in both regimes: max |Δ turb-down| = 0.0 fps against the write-once
run, bit-identical realisation. Per-step writes as such are safe.

**The W20 route (below the ~300 m AGL ceiling) is sane.** Stepped schedule
none → light → moderate → severe, seed once, windowed σ_w vs a
constant-intensity run of the same seed: ratios 1.00×, 1.03×, 0.97×. A
*continuous* W20 ramp 15 → 45 kt tracks σ_w ≈ 0.107·W20(t) window by window
(4.52/4.06, 6.32/6.10, 8.15/8.13 fps measured/expected), peak |n_z−1|
0.60 g. No overshoot, no restart artifacts.

**The POE route (above the ceiling) is NOT sane for mid-run changes.**
Changes *from* severity 0 land exactly (first schedule block ratio 0.9999);
every subsequent nonzero → nonzero change overshoots. Measured at 1000 m,
seed 17, σ_w over the 4–20 s window after the switch:

| transition | commanded index (ladder σ_w) | measured σ_w | settles |
|---|---|---:|---|
| 0 → 3 at t=20 | 3 (7.729 fps) | 9.03 fps | already correct |
| 2 → 3 at t=20 | 3 (7.729 fps) | **22.43 fps** | 7.93 fps by t=40–60 |
| 0 → 2 → 3 | 3 (7.729 fps) | **39.98 fps** | 9.08 fps by t=40–60 |
| ramp 2 → 4 over 40 s | 3–4 (7.7–11.0 fps) | **29.17 fps** | still 14.9 fps 20 s after |

The overshoot is 2–5× the commanded level and takes tens of seconds to
decay — indistinguishable, from inside a run, from severe turbulence that
was never commanded. **Fractional severity does not interpolate**: constant
severity 2.5 delivers σ_w 3.61 fps, identical to 2.0 (floored), so a smooth
coupling cannot even be expressed on this axis.

**Severity 0 is a master off-switch, and its nonzero value is irrelevant
below the ceiling.** Measured at 150 m AGL with W20 = 30 kt: severity 0
delivers σ_w = 0.000 fps — it silences the W20 route as well — while
severity 1 and severity 3 both deliver the identical 5.481 fps
(= 0.108·W20, the low-altitude relation). A W20-driven provider must
therefore pin severity to a nonzero constant (1 is the floor) at configure
time and never touch it again.

Consequence: any provider that varies turbulence intensity mid-run drives
**W20 only**, with severity pinned to a nonzero constant, and the coupling
is valid **below the 300 m AGL ceiling only**; above it, where W20 is
ignored (§9), the process delivers the constant POE ladder value of the
pinned severity (1.785 fps at index 1) — a stated boundary the provider's
vocabulary must carry, not a claim the coupling still holds.

---

## 14. The dew point is capped silently, twice, against the LAST computed state

`atmosphere/dew-point-R` is not stored as written. `FGStandardAtmosphere::SetDewPoint`
converts it to a vapour pressure (the Magnus form, a = 611.2 Pa, b = 17.62,
c = 243.12 degC) and `SetVaporPressure` to a vapour mass fraction using the
pressure of the LAST `Calculate`; `ValidateVaporMassFraction` then caps the
fraction at saturation -- against the saturated vapour pressure of the last
computed TEMPERATURE -- and at a per-altitude table of record-high fractions
(35000 ppm at sea level, 38 ppm at 16 km), looked up at the PRESSURE altitude on
the write and at the geometric altitude on every step. Each cap prints a line to
the C++ stderr and raises nothing. Measured on 1.2.4: `dew-point-R` 540 written
at ISA sea level reads back 518.67 (RH 100 %); a dew point of 10 degC written
together with a +20 degC `delta-T` before any recomputation is capped at the
pre-bias 5.25 degC ("Dew point temperature has been capped to 501.124"); 500 R
written at 5000 ft reads back 499.63 R (the table). A dew point read back AFTER a
step also differs from the one written by one step's pressure change (1.5e-6 R
per step on a c172p at 1500 m): the mass fraction, not the dew point, is what
JSBSim conserves.

Consequences (core/environment/atmosphere.py): write `delta-T` and `P-sl-psf`
first and recompute (`run_ic` before the trim; a step during the flight) before
writing the dew point; never write a dew point above the temperature JSBSim
currently holds or beyond the table's dew point at the current pressure; refuse
both by name at the scene (`atmosphere.dew_point`) rather than let the cap print;
and grade the per-step read-back of the dew point at 1e-6 relative with the
reason stated, the other two properties at zero.

---

## 15. A `<system>` reads the previous step's `aero/alpha-rad`; an aerodynamics `<function>` reads this step's (measured 2026-09-28, P2)

In the 1.2.4 schedule the Systems model runs before FGAuxiliary, so an `<fcs_function>` in a `<system>` that copies `aero/alpha-rad` holds the PREVIOUS step's alpha: measured on a trimmed c172p under an elevator step, the copy lags by 5.3e-4, 6.7e-4, 9.8e-4, 1.26e-3, 1.52e-3 rad over five steps (6.8e-9 rad even on the trim's first step). A `<function>` declared at the top of `<aerodynamics>` is evaluated by FGAerodynamics before the axes with the current alpha: difference 0.0 at every step. The icing stall-onset shift (`core/control/derive.py`, injection `icing_alpha`) therefore computes `icing/alpha-effective-rad` as a pre-axis aerodynamics function, not as a system, and its neutral value is bit-identical to the stock airframe because of it.

## 16. `atmosphere/turb-*-fps` is never externally writable: a write is overwritten on the next step (measured 2026-09-28, P6)

The three turbulence properties are bound read-write (`FGWinds.cpp` v1.2.4 L559-L564, `SetTurbNED`), and a write lands: `atmosphere/turb-north-fps` written 10 reads 10.0 before any step. But `FGWinds::Run` (L145-L150) recomputes `vTurbulenceNED` every step -- `Turbulence(in.AltitudeASL)` when `turb-type` is not 0, `vTurbulenceNED.InitMatrix()` when it is -- so the written value never reaches the total wind. Measured on the trimmed c172p (1500 m, 100 kt, 120 Hz): with `turb-type` 0, 10 fps written reads 0 after one step and 0.0 on each of five steps rewritten every step; with `turb-type` 4 (ttTustin, severity 3, W20 25 fps) the same write reads 0.0182 after one step and the Dryden process's own values (0.031, -0.043, -0.264, -0.314, -0.095) on the rewritten steps. Consequence: a Python-realised turbulence field (the von Karman table, `core/environment/von_karman.py`) cannot be delivered through the turbulence channel at all; it goes through the gust channel (17). `atmosphere/p-turb-rad_sec` is bound read-only (L566) and cannot carry a roll gust either: that is the `gust/p-equivalent-rad_sec` injection's job (P2).

## 17. `atmosphere/gust-*-fps` PERSISTS until written again, so a gust provider must write every step, zero included (measured 2026-09-28, P6)

`vGustNED` is never reset by the model: `Run` (L157) forms `vTotalWindNED = vWindNED + vGustNED + vCosineGust + vTurbulenceNED` from whatever the property holds. Measured on the trimmed c172p: `atmosphere/gust-north-fps` written 7.0 once reads 7.0 on every one of 11 steps and `total-wind-north-fps` reads 6.999999999999574 (the wind's -4.3e-13 added); written 0.0 it reads 0.0 and the total -4.3e-13 again; beside an active Dryden process (ttTustin, 20 steps) the total equals wind + gust + turb to 0.0 (5.5013 = -4.3e-13 + 7.0 + -1.4987). The channel is therefore additive and durable: a provider whose gust has passed and that stops writing would leave its last value blowing for the rest of the flight. Consequence (`core/environment/stack.py`): the stack sums every gust provider and writes the three properties EVERY step -- 0.0 when there is no provider -- and reads each back before the next write (0.0 error on every step of a 3 s von Karman run, 359 of 360 steps checked). A stack with no gust provider writing 0.0 into a channel that already holds 0.0 changes nothing: every pre-existing recorded column of four c172p/A320 runs is bit-identical to HEAD's (worst |diff| 0.0), measured from a `git archive` of HEAD.

## 18. `FGWinds.h` says "turb-type 4 resp. 5"; the enum is ttMilspec = 3, ttTustin = 4 (measured 2026-09-28, P6)

The class comment (`FGWinds.h` L78-L79, vendored copy identical to the fetched v1.2.4 source) reads "To use one of these two models, set atmosphere/turb-type to 4 resp. 5", one above the enumeration two lines earlier in the same comment (L63-L67: 0 ttNone, 1 ttStandard, 2 ttCulp, 3 ttMilspec, 4 ttTustin) and the enum itself (L183: `enum tType {ttNone, ttStandard, ttCulp, ttMilspec, ttTustin}`; L248 lists a `ttBerndt` that the enum does not carry). Measured on the trimmed c172p (severity 3, W20 25 fps, seed 1, 600 steps): turb-type 3 reads back 3.0 and delivers a peak |turb-down-fps| of 9.80; 4 reads back 4.0 and delivers 8.13; 5 reads back 5.0 and delivers 0.0000 -- the number the comment names is off the end of the enum and produces no turbulence. This closes docs/VALIDITY.md section 4's open item: `core/environment/turbulence.py`'s TURB_MILSPEC = 3 and TURB_TUSTIN = 4 are right, the header comment is wrong. Two further facts from the same reading: the Dryden ladder is entered with the altitude above SEA LEVEL (`Run` passes `in.AltitudeASL`, L145; MIL-F-8785C's h is height above ground), and JSBSim's own trim resets `atmosphere/wind-*-fps` to 0 (33.756 fps written before `do_trim` reads 0.0 after a longitudinal trim and -4.8e-16 after a full trim, the trimmed throttle 0.7392 and pitch 0.386 deg identical with and without the wind), so a wind written before the trim -- the branch's steady wind and P6's profile alike -- is NOT what the trim solves in; the first per-step write restores it (an open item, see the P6 report).

## 19. A turbine's `set-running = 0` relights on the next step; JSBSim's cutoff holds (measured 2026-09-28, P3)

The blueprint's engine-out write, `propulsion/engine[i]/set-running = 0`, gives ONE step of no thrust on the A320 at 1500 m / 250 kt: 11943.05 lbf trimmed, 0.000 on the next step, 11942.99 on the step after and 11942.96 at 5 s. `FGTurbine::Calculate` (FGTurbine.cpp v1.2.4 L146-L147) enters `tpStart` while `Cutoff` is false and qbar exceeds 30 psf (210 psf here), and `Start()` (L292-L309) relights with N2 above idle. JSBSim's own cutoff holds: `propulsion/active_engine = i`, `propulsion/cutoff_cmd = 1`, `propulsion/active_engine = -1` (FGPropulsion.cpp L651-L680 `SetCutoff`, the ties at L814 / L823) puts the engine in `tpOff` (L150), whose `Off()` (L175-L196) returns 0 thrust with `Running` false: 0.000 lbf on every one of 600 steps, `set-running` 0.0, N1 83.66 -> 50.69 % at 1 s -> 19.89 % at 5 s, engine 1 untouched (11924.65 lbf). Blueprint correction 8 ("cutoff_cmd is ignored after a trim") holds only for a write BEFORE the first post-trim step (L125-L138 reset `Cutoff = false` on the `tpTrim -> tpRun` transition); a scheduled write lands later and sticks. Consequence (`core/telemetry/failures.py`): the turbine engine-out is the cutoff, bracketed by `active_engine`, read back with the engine re-selected. The ladder's A320 pair (docs/vva/VV_REPORT.md section 1b) reads 0.0 N on all 19 samples after the write against 53 kN without.

## 20. A piston's `set-running = 0` is relatched by the windmilling propeller (measured 2026-09-28, P3)

On the c172p `propulsion/engine[0]/set-running = 0` reads 1.0 on the next step: FGPiston.cpp L595-L598 sets `Running` again while the propeller windmills above 0.8 x idle rpm. The magneto cut holds: `propulsion/magneto_cmd = 0` (FGPropulsion.cpp L598-L614) removes the spark (FGPiston.cpp L569-L573), `Running` is false on the next step (L592-L594) and the power falls 89.1 -> -3.5 hp at once; the thrust then dies on the propeller's inertia -- 226.7 lbf halved at 0.39 s, 10 % at 1.30 s, through zero at 1.68 s, about -40 lbf of windmilling drag at 4 s; rpm 2300 -> 1386 (2 s) -> 823 (5 s) -> 697 (8 s) -> 686 (10 s). The mixture cutoff (`fcs/mixture-cmd-norm = 0`) gives the same die-off to 0.3 %. Consequence: the piston engine-out is the magneto cut, and its null test grades the thrust 2 s after the write, not on the next step.

## 21. `propulsion/magneto_cmd` is write-only (measured 2026-09-28, P3)

The tie at FGPropulsion.cpp L819-L820 binds a setter and NO getter (the catalog lists the property `(W)`): a value written cannot be read back. A piston engine-out is therefore read back through the state it implies, `engine[i]/set-running` 0.0 on the next step, and the record says so.

## 22. JSBSim's clock at a run's first step is the engine start's cranking time, and it depends on the rate (measured 2026-09-28/29, P3, P5, P8)

A piston's start cranks for seconds before the trim: the c172p's first recorded sample is at 4.875-4.933 s of sim time, the A320's one step in (0.0083 s at 120 Hz). The crank ends on a step, so the start time differs between rates: 4.933 / 4.900 / 4.879 s at 60 / 120 / 240 Hz on the committed c172p example. Consequences: a scheduled time (a failure's `at_s`, the icing onset) counts on the RUN clock, seconds since the first step, with the sim time recorded beside it; and two recordings at different rates are compared on each run's own elapsed time -- compared on the raw clock, the three-rate study measured the crank's phase shift (0.048 m of altitude at 60 vs 120 Hz) instead of the integration error (0.0019 m), and `core/uncertainty.py` now aligns both clocks at their first sample.

## 23. A jam (`fail_stuck`) holds the output of the step BEFORE the failing one (source read 2026-09-28, P3)

FGActuator.cpp v1.2.4: `fail_zero` replaces the input by 0 (L150), `fail_hardover` by ClipMin / ClipMax by the input's sign (L151), and `fail_stuck` outputs `PreviousOutput` (L160-L161, kept at L171) -- the value of the previous step, not the command at the step the switch was set. Measured: the jammed A320 elevator holds -0.12645121403107676 rad with drift 0.0 over 100 steps while TECS moves the command; the ladder's jam reads 0.0 drift again.

## 24. Mass properties and the aerodynamic forces at the ICs are stale until a model pass (measured 2026-09-28/29, P4, P5)

`inertia/pointmass-weight-lbs[i]` and `propulsion/tank[i]/contents-lbs` are read-write and hold a write to the bit, but FGMassBalance recomputes only on a model pass: 300 lb written to the c172p's baggage station leaves `inertia/cg-x-in` at 42.11702 in until `run_ic`, after which it reads 49.39450 in. The same holds for the aerodynamics: an icing factor of 0.8 written into an injected `<product>` wrap leaves `forces/fwz-aero-lbs` at 1476.19 lbf until `run_ic` (1183.91 lbf after), and each further `run_ic` moves the cranked c172p's IC lift by about 0.1 lbf (the DHC6's by 0.0). A write AFTER the trim leaves the trim solved for the old aircraft: 300 lb at the baggage station after the trim keeps the elevator at 4.3061 deg and the c172p pitches 0.386 -> 9.722 deg and climbs 20.0 m in 5 s at the trim controls. Two more from the same measurements: a tank's capacity is not a property (it is recovered as 100 x contents / `pct-full`, equal to the configuration to 1e-9 on five airframes), and the p51d's twelve weapon stations are `<output>`s of `Systems/weapons-weight.xml` (300 lb written reads 0.0 after one pass). Consequence: every pre-trim write is followed by a re-latch before it is read, and loading is written before the trim.

## 25. `atmosphere/sigma` is the ratio to the DAY's sea-level density; the standard sea-level pressure is 101325.54 Pa (measured 2026-09-28, P1; 2026-09-29, P8)

JSBSim's `atmosphere/sigma` divides by the sea-level density of the modelled day, not of the standard one: 1.0 at sea level with `delta-T` +30 degC. A hot day's density ratio is therefore compared through `atmosphere/rho-slugs_ft3`, never through that property (`core/environment/atmosphere.py` computes its own `sigma` against the standard day). JSBSim's standard sea-level pressure is 2116.228 psf; 1013.25 hPa converted with JSBSim's own 47.880258980336 psf-to-Pa factor is 2116.2166 psf, 5.4e-6 lower, so the standard day at sea level reads 101325.54 Pa -- 0.54 Pa above the 1976 table's printed 101325, the one cell of row A8 (docs/vva/VV_REPORT.md) besides the 3000 m density that sits outside the table's half-digit. Otherwise JSBSim's standard day matches the 1976 table within 1.2e-5 relative at 0 / 3000 / 11000 m.

## 26. JSBSim's Dryden channel does not deliver its own ladder sigma (measured 2026-09-28, P6)

With `turb-type` 4 (ttTustin) and the severity row 3 at 1500 m the ladder sigma_w is 7.181 ft/s (2.189 m/s, FGWinds.cpp L273-L288). Sampled at 10 Hz over 60 s at seed 7 with the controls held on the c172p, the delivered `atmosphere/turb-*-fps` std is 2.39 / 15.21 / 4.07 m/s (north / east / down): the vertical channel 1.9 x the ladder, the lateral 7 x (over 600 s, the aircraft descending, 2.92 / 12.41 / 2.99 m/s; ttMilspec 2.83 / 2.70 / 1.69). The ratio on w is platform-dependent because the process draws from the C++ library's generator: 1.86 on Linux, 2.13 on Windows, 2.60 on macOS (CI run 36503916763). Consequence: "the same sigma" for the von Karman and Dryden models holds at the COMMANDED ladder only; the von Karman field (delivered through the gust channel, 17) realises it within 0.7 % over a 3 s flight (row A9) and the Dryden channel does not.

## 27. A stated non-standard day keeps the initial TRUE airspeed, so the CAS flown is not the CAS stated (measured 2026-09-29, P8)

`FGInitialCondition` holds the velocity as a true airspeed: `ic/vc-kts` is converted to TAS with the atmosphere at the moment it is set. The non-standard atmosphere writes `delta-T`, `P-sl-psf` and `dew-point-R` AFTER the initial conditions and re-latches with `run_ic`, which keeps that TAS. Measured on the c172p at 1500 m with 100 kt stated: at `delta-T` +30 degC the trimmed first sample reads TAS 107.537 kt (equal to the standard day's to 3e-13 kt) and CAS 95.83 kt; at 100 % RH, CAS 99.80 kt. TAS / CAS still equals 1 / sqrt(sigma) within 0.06 % in both runs (0.046 % and 0.056 %, the ladder's delta-T row), so the atmosphere is right and the airspeed is the one that moved. Consequence: on a stated day the spec's calibrated airspeed is not the one flown, and V2 (every requested IC within 1e-3 relative) does not hold for CAS there -- an open defect for the atmosphere provider (re-set `ic/vc-kts` after the day's writes, or verify the IC after `prepare`), recorded here and in docs/VALIDITY.md section 2.27.

## Model envelope boundaries (measured, not published)

Where each stock model's aero tables give out, from `experiments/envelope_probe.py`.
This is a property of the tables and says nothing about the real aircraft.

| Model | 3000 m | 6000 m | 10000 m |
|---|---|---|---|
| global5000 | 200–300 kt CAS | 200–300 | 200–240 (fails above M0.68) |
| 737 | 200–300 | 200–300 | 200–280 (fails above M0.79) |
| B747 | 200–300 | 200–300 | 200–300 (reaches M0.835) |

Trim failure at the edge is correct behaviour. Gate 0's grid is chosen inside
every candidate's envelope so the airframes are compared on equal terms.

The boundaries the physics additions measured (2026-09-28/29, JSBSim 1.2.4,
120 Hz) are of another kind -- where a model, a derivation or the trim stops
doing what a write asks -- and each is a refusal or a stated limitation in
the code, not a silent path:

| Model | Boundary | Measured | Consequence |
|---|---|---|---|
| DHC6 | Its engine, propeller and system files live in aircraft-local `Engines/` and `Systems/`; JSBSim resolves `<thruster file="Propeller">` against the aircraft directory's `Engines/` first | A derived DHC6 did not load ("Could not open file: Propeller") until `core/control/derive.py` copied the local subdirectories (P5); the derived hashes are unchanged | Derivation copies them; the DHC6 flies icing |
| DHC6 | FCS in a shared `<system file=...>` | The failures injection cannot anchor (P2) | `derivation.anchor_missing` / `failures.actuator_missing`: no surface failure on the DHC6 |
| A320 (turbine) | `set-running = 0` in flight | Thrust 0 for one step, then 11942.99 lbf: relit (section 19) | Engine-out is the cutoff |
| c172p (piston) | `set-running = 0` in flight | Relatched on the next step by the windmilling propeller (section 20) | Engine-out is the magneto cut |
| every model | A wind written before `do_trim` | Reset to 0 by the trim (33.756 fps -> 0.0 / -4.8e-16), the trimmed throttle identical with and without (section 18) | "Trimmed in the wind" is trimmed in still air; the first per-step write restores the wind (stated) |
| every model | A stated day written after the initial conditions | The IC's TAS is kept: 100 kt CAS stated flies 95.83 kt CAS at +30 degC on the c172p (section 27) | Open defect, stated |
| c172p | The autopilot's sign probe trims at 6000 m / 280 kt | `TrimError` (udot not trimmable) | The c172p flies open loop in every physics test and the ladder; an elevator jam cannot diverge it (silent by construction) |
| c172p | A static stall sweep through the lift table | Lift peak at 16.25 deg requested (CL 1.449) | The stall-onset cue is measured as a -2.0 deg move of that peak |
| p51d | Lift table in alpha DEGREES; weapon stations are system outputs | `icing_alpha` cannot anchor; 300 lb written to a weapon station reads 0.0 (section 24) | `derivation.anchor_missing`; the stations are configured unloadable |
| f16 | Five alpha-rad lift tables; the aileron command read by a `<test>` | The failures and `icing_alpha` injections cannot anchor | Refused by name |
| B747 | Aileron term a Mach table | The wake's roll-control ratio cannot be computed | Recorded `absent` with the reason |
