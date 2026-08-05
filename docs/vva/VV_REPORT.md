# Verification & Validation Report

Results against the criteria declared in [VV_PLAN.md](VV_PLAN.md). Every number
here was measured on the pinned build (JSBSim 1.2.4, Python 3.9.6, macOS).

## 1. Verification results

| # | Activity | Result | Evidence |
|---|---|---|---|
| V1 | Trim equilibrium | **PASS** 9/9 conditions. Altitude excursion 1.3–4.2 m, CAS 0.09–0.22 kt, roll 0.00°, oscillation **shrinking** in every case | Gate 0 |
| V2 | Initial-condition fidelity | **PASS**. Two order-dependency defects found and guarded (see §3) | Gate 0/1 |
| V3 | Spec reproducibility | **PASS**. Identical SHA-256 over all telemetry across reruns | Gate 1 |
| V4 | Envelope validation | **PASS**. Rejections by name: `altitude.terrain_clearance`, `airspeed.stall_margin`, `envelope.trim_feasible` | Gate 1 |
| V5 | Control step response | **PASS** with documented deviation (§4). Altitude +100 m: 10.1% overshoot, 0.000 m SSE. Airspeed +15 kt: 6.2%, settles 53.5 s. Bank +30°: 2.8 s rise | Gate 2 |
| V6 | Loop decoupling | **PASS**. Commanding both: altitude overshoot 10.1→12.8%, airspeed overshoot *falls* 6.1→1.1%. Both stay inside their own acceptance | Gate 2 |
| V7 | Closure | **PASS**, and demonstrated *failing* on an unachievable command | Gate 2 |
| V8 | Environment connectivity | **PASS** 5/5. Settled crab 4.96° vs atan(25/288) = 4.96° predicted | Gate 3 |
| V9 | Numerical convergence | **PASS**. Peak altitude difference 0.098 m (1/60↔1/120), 0.048 m (1/120↔1/240) — halving as the step refines | Gate 3 |
| V10 | Terrain round trip | **PASS**. 0.008 m max error; relief preserved to 0.000 m; aspect to 1 part in 10⁹ | Gate 4 |
| V11 | Sweep integrity | **PASS**. Killed at case 7 of 18; resumed skipping exactly 7; dataset matches case-for-case | Gate 7 |
| V12 | Provenance | **PASS**. Physics bit-identical across all 18 cases on replay from the manifest | Gate 7 |

Gate 5 (host parity) is **BLOCKED**: the Unreal host does not build on this
machine because the installed Xcode is outside UE 5.5's supported range. Not
attempted, not failed.

## 2. Validation results

| # | Quantity | E | u_val | Verdict |
|---|---|---|---|---|
| A1 | B747 clean 1g stall, 250 t | −2.4 kt | 12.4 kt | validated at u_val |
| A2 | Turbulence σ_w vs W20 | measured 0.107·W20 vs 0.1·W20 | — | validated |
| A3 | Takeoff ground roll | — | — | **inconclusive** — no referent |
| A4 | Engine spool time | — | — | **inconclusive** — no referent |
| A5 | Short-period damping | — | — | **not attempted** — no linearisation |
| A6 | Transport delay | — | — | not applicable |

**Most of this table is inconclusive, and that is the result.** A1's agreement
is real but weak evidence: one point, on one airframe, against a specification
figure with a deliberately wide u_D. Reporting it as "validated at u_val" rather
than "validated" is the distinction that matters.

## 3. Defects found by verification

Each of these produced a plausible-looking wrong answer rather than an error.
Full measurements in [../JSBSIM_CORRECTIONS.md](../JSBSIM_CORRECTIONS.md).

1. Unknown property names write successfully and never reach the FDM.
2. `ic/lat-geod-deg` overwrites `ic/vc-kts` — 300 kt CAS at 10 km became Mach 1.28.
3. `ic/beta-deg` overwrites `ic/psi-true-deg` — heading 270 became 000.
4. Aircraft load with engines stopped; thrust cannot distinguish running from stopped at idle.
5. Lift sign: inverted gives CLmax 0.104 and a **526 kt** stall for a 747.
6. §6.4's `/(g·τ)` normalisation is dimensionally an acceleration where an angle is needed.
7. JSBSim imposes no control-sign convention — hardcoding one gave positive feedback and NaN in 89 s.
8. FCS channels run while "disengaged", so engaging dumped wound-up integrators onto the surfaces (33 m lost).
9. Re-seeding turbulence per step destroys the process: peak load factor 0.40 g → **515 g**.
10. Closure averaged headings arithmetically; jitter across 0°/360° averaged to 180°.
11. Reprojection corners filled with fabricated terrain: slopes to 84.9° where p99 of real data is 23.3°.
12. Non-square DEM into a square Landscape squashed the ground by 1.47× while every elevation still read back correctly.
13. **Seeds ≥ INT_MAX saturate to 2147483647**, so sweep replicates ran identical realisations while the manifest recorded different seeds.

Defect 13 was found by the degenerate-replicate detector, which is exactly what
§8 said that machinery was for.

## 4. Documented deviations from the brief

| Deviation | Reason |
|---|---|
| Gate 0 asserts on a mass-held run | A fuel-burning aircraft has no equilibrium; fuel burn is the entire residual drift (737: +89.6 m burning, +2.00 m held) |
| Settling referenced to phugoid period, not 3–5·τ | Sweeping the pitch inner loop over 12 gain combinations moved altitude settling by <1 s; the phugoid governs it |
| "Neither channel worse" read as "neither leaves its acceptance" | Climbing and accelerating draw on one energy budget; literal non-degradation is unachievable |
| Turbulence intensity via POE index, not W20 alone | Measured: above ~300 m AGL, W20 has **no effect**; the POE index governs |

## 5. Conclusion

Verification is substantially complete for the headless system and the evidence
is reproducible. **Validation is not, and cannot be with stock aerodynamic
data.** The system is fit for the comparative, within-model research use
described in [ACCREDITATION.md](ACCREDITATION.md), and unfit for any absolute
performance claim.
