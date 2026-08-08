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
