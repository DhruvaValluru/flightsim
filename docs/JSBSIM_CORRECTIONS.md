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

## 7. Environment hazard: bytecode is cached outside the repo

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
