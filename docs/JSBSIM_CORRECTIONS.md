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

## 2. `ic/vc-kts` is silently overwritten by `ic/lat-geod-deg`

**The most dangerous finding.** Initial conditions are order-dependent. Setting
geodetic latitude *after* an airspeed re-derives the velocity state and
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

Guarded by two independent mechanisms, because ordering alone rots the moment a
new IC key is added:
1. `_IC_PRIORITY` in `core/fdm/fdm.py` fixes a safe order (position first,
   velocity last).
2. `_verify_initial_conditions` compares every requested condition against the
   state actually achieved and raises on a mismatch.

Test: `tests/test_initial_conditions.py` (parametrised over four altitudes,
plus a deliberately hostile dict order).

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
