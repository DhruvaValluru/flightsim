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
| V13 | Loading: the hand CG | **PASS**. Hand CG − `cg-x-in`: c172p 7.1e-15 in, A320 0.0, B747 6.8e-13, DHC6 2.8e-14, p51d 1.4e-14 (tolerance 0.1 in). The c172p arm test is **inferred, not verified**: XML and handbook seat arms differ by up to 3 in (the handbook arms from memory), so the XML datum is taken as the handbook's with a 3 in uncertainty. Gate 3b: 136 kg at the aft seat moves the CG 0.0974 m, read back within 0.1 in | P4, tests/test_loading.py; Gate 3b |
| V14 | Limit monitoring self-trip | **PASS** for the speed limit on real flights: A320 at 370 kt flags 96/96 samples beyond V_MO (worst margin −20.00 kt), at 250 kt 0/96. The n_z trip is measured on synthetic columns only (1.4 g pushed to 3.0 g flags against 2.5 g). **NOT RUN**: a flown 4 g pull-up, and the verifier's recomputation (verify.py has no limits clause) | I2, tests/test_limits.py |
| V15 | Failure timing | **PASS**. t_applied − t_s in [0, dt): c172p 5e-14 s, A320 one dt (0.00833 s); jam drift 0.0 rad over 100 steps (c172p rudder, A320 elevator); turbine cutoff thrust 0.0 on every one of 600 steps; authority 0.5 holds −0.15 on 100 steps, drift 0.0; every write read back (14 of 14). Gate 3b: A320 thrust 0.0 N on 19 of 19 samples after the write, jam drift 0.0 | P3, tests/test_failures.py; Gate 3b |
| V16 | Wake field | **PASS**. V(r_c) = Γ/(4π r_c) to 1e-14; far field falls 100.0× between 100 b_0 and 1000 b_0 (a dipole) and equals Γ b_0/(2π r²) to 1e-4; divergence ≤ 3.1e-8 1/s; p_eq(uniform w) = 0 and p_eq(p·y) = p to 1e-12; 32-point quadrature within 1e-7 of a 200000-point rule. Gate 3b: encounter rolls 31.05° more than without in 3 s, the far control silent | P7, tests/test_wake.py; Gate 3b |
| V17 | Layered wind | **PASS**. 22.5 kt from 255° at 1500 m for the test layers, layer 1, dV/dz 0.0077 1/s; held beyond the end layers. Gate 3b: delivered 11.56385 m/s against the interpolation's 11.56378 at the last sample (7.2e-5 m/s) | P6, tests/test_shear.py; Gate 3b |
| V18 | Derivation bit-identity | **PASS on the c172p**: 8 s of an elevator step, 960 steps, 15 properties, worst \|derived − stock\| 0.0 per injection and all four together; anchors refused by name (DHC6 failures; f16 failures, icing_alpha; p51d icing_alpha). **NOT RUN** per airframe beyond the c172p (the A320 and B747 derive with all four; not compared bit for bit) | P2, tests/test_derive_injections.py |
| V19 | Atmosphere read-back | **PASS**. `delta-T` and `P-sl-psf` read back 0.0 before the trim and every step; the dew point within one step's pressure change (1.5e-6 R over 360 steps, c172p; 2.3e-7 R over 600, A320; tolerance 1e-6 relative); `delta-T` survives 200 unrewritten steps; the delivered state equals the closed form to 1e-13. Gate 3b: TAS/CAS within 0.046 % / 0.056 % of 1/√σ at ΔT +30 / 0 | P1, tests/test_atmosphere.py; Gate 3b |
| V20 | Gust channel | **PASS**. Two constant providers of 1 and 2 m/s read 3 m/s on the channel and 4 + 3 m/s in the total wind (1e-9 fps); an empty stack writes 0 after a 7 fps write; per-step read-back 0.0 on 359 of 360 steps; every pre-existing column of four HEAD runs bit-identical | P6, tests/test_gust_provider.py |

Gate 5 (host parity) is **BLOCKED**: the Unreal host does not build on this
machine because the installed Xcode is outside UE 5.5's supported range. Not
attempted, not failed.

### 1b. Gate 3b: the physics layers' null ladder

`.venv/bin/python -m experiments.gate3b_layers`, run once on 2026-09-29 at
commit f371c46 with the advancement additions uncommitted in the tree
(Linux x86_64, Python 3.11.15, JSBSim 1.2.4 [GitHub build Feb 7 2026]; the
manifest records `dirty: true`), 3 s flights. Manifest
`runs/gate3b/manifest.json` sha256
`ddf7feab4059bc0affaf790efbd4fdd6aa30bd68b857f0a40ff230936af2f4a7`; its
output `gate3b_layers.json` sha256
`179da043d676244358b8424821bb1a92876923e170b68267fc98c6ac721fb619`.
**12 PASS, 0 FAIL, 0 NOT RUN.** Every pair's output digests differ.

| Rung | Verdict | Effect (peak \|with − without\|) | Criterion, measured | Status |
|---|---|---|---|---|
| delta-T +30 vs 0 | reached | density altitude 847.60 m, temperature 30.000 K, TAS 0.0037 kt (below floor) | TAS/CAS 1.12218 vs 1/√σ 1.12270 (0.046 %); at 0: 1.07537 vs 1.07598 (0.056 %) | **PASS** |
| dry vs 100 % RH | reached | RH 100.0 %, e 887.17 Pa, density altitude 39.99 m | row A7 | **PASS** |
| vK vs none | reached | gust n/e/d 3.40 / 3.95 / 3.43 m/s, altitude 0.591 m, roll 4.47° | row A9 | **PASS** |
| vK vs Dryden | reached | gust 3.40 / 3.95 / 3.43 m/s, altitude 0.505 m, roll 4.55°, p_eq 0 (stock airframe, below floor) | the ladder σ_w 2.189 m/s commanded to both; vK delivers 2.174 (0.7 %); Dryden's own channel NOT RUN here (P6: 1.9× on w over 60 s) | **PASS** |
| encounter vs none | reached | roll 31.05°, roll rate 17.15 °/s, altitude 2.29 m, p_eq 0.2392 rad/s, w 3.11 m/s | peak roll difference 31.05° > 5° (with 36.63°, without 5.58°: the open-loop c172p rolls on its own) | **PASS** |
| far control (300 m) | silent | roll 0.027°, altitude 0.032 m, w 0.031 m/s, p_eq 2e-4 rad/s: all under their floors | the wake present (Γ_0 338.17 m²/s), the pair silent | **PASS** |
| η 0.2 vs 0 | reached | lift 100.41 N, drag 75.53 N, pitch 0.134°, TAS 0.40 kt; altitude 0.25 m (below floor) | lift at fixed α 0.98223 vs 1 + 0.2 × (−0.09) = 0.982 (0.023 %); first iced sample 0.98794 (the alphas part) | **PASS** |
| 136 kg aft seat vs none | reached | CG 0.0974 m, elevator 0.223°, pitch 0.548°, weight 136.0 kg, I_yy 73.1 kg m² | all three past their floors; CG read back within 0.1 in of the hand value | **PASS** |
| A320 engine-out vs none | reached | TAS 3.14 kt, heading 0.39°, pitch 0.17°; altitude 0.27 m (below floor) | thrust 0.0 N on 19/19 samples after the write, ≥ 53.1 kN without | **PASS** |
| A320 jam (TECS, turbulence) vs none | reached | pitch 1.31°; altitude 0.24 m, TAS 0.065 kt, heading 0.010° (below floors) | the jammed elevator held at −0.12829 rad, drift 0.0 over 100 steps | **PASS** |
| layered vs uniform | reached | wind speed 1.2865 m/s, dV/dz 0.0077 1/s, altitude 3.43 m | delivered 11.56385 vs 11.56378 m/s (7.2e-5) | **PASS** |
| A8 (no pair) | — | — | row A8 | **PASS** |

**The ladder found a defect the layers' own tests did not.** A stated day
keeps the initial TRUE airspeed: the c172p asked for 100 kt CAS flies 95.83
kt CAS at ΔT +30 °C (99.80 kt at 100 % RH), TAS 107.537 kt on both sides to
3e-13 (docs/JSBSIM_CORRECTIONS.md §27). The atmosphere is right (TAS/CAS
matches σ); the stated airspeed is not what is flown, so V2 does not hold
for CAS on a stated day. Open.

**The three-rate study** (`.venv/bin/python -m experiments.gate3b_convergence`,
same tree, the committed c172p example, 1200 m / 100 kt CAS open loop,
turbulence off, 10 s at 60 / 120 / 240 Hz; manifest
`runs/gate3b/convergence_manifest.json` sha256
`10788192fca6417b5c139f6fcf666655a88df78df92732bf26370cd1b6559b11`; the
study `data/convergence/gate3b_convergence.json` sha256
`d96ca6b39d859c21a8a01cb04af49468d09cf9c719ea25feda4231d9828d45d1`):

| SRQ | e(60↔120) | e(120↔240) | observed p | used by u_num |
|---|---|---|---|---|
| altitude | 1.908e-3 m | 8.442e-4 m | 1.18 | 1 (capped at the formal order) |
| north | 1.212e-3 m | 9.127e-4 m | 0.41 | 0.41 |
| east | 1.060e-2 m | 6.840e-3 m | 0.63 | 0.63 |
| TAS | 4.606e-4 kt | 2.462e-4 kt | 0.90 | 0.90 |
| pitch | 7.092e-4° | 3.056e-4° | 1.21 | 1 (capped) |
| roll | 3.589e-3° | 3.832e-3° | −0.09 | none: not converging, p = 1 assumed with Fs = 3 |
| heading | 3.979e-3° | 2.733e-3° | 0.54 | 0.54 |

The first run of the study compared the three recordings on JSBSim's raw
clock and read p ≈ 0.6 on every SRQ with an altitude e(60↔120) of 0.048 m:
the c172p's crank ends on a rate-dependent step (first sample at 4.933 /
4.900 / 4.879 s), so the comparison measured a phase shift. core/uncertainty.py
now aligns both clocks at their first sample (the dt/2 twin too); the table
is from that. The JSBSim default integrators are first order (rotational
rate and attitude by rectangular Euler, read from the property tree), so an
observed order above 1 is used as 1; u_num reads the study only for a run of
the same c172p file on the same JSBSim at 60 or 120 Hz, and keeps p = 1,
Fs = 3 otherwise. V9's B747 altitude order (1.03) and this c172p altitude
order (1.18) are consistent; the lateral SRQs of an open-loop flight
converge more slowly, and roll not at all over 10 s.

## 2. Validation results

| # | Quantity | E | u_val | Verdict |
|---|---|---|---|---|
| A1 | B747 clean 1g stall, 250 t | −2.4 kt | 12.4 kt | validated at u_val |
| A2 | Turbulence σ_w vs W20 | measured 0.107·W20 vs 0.1·W20 | — | validated |
| A3 | Takeoff ground roll | — | — | **inconclusive** — no referent |
| A4 | Engine spool time | — | — | **inconclusive** — no referent |
| A5 | Short-period damping | S only, no D: ζ_sp 0.610 / ω_sp 7.01 rad/s (c172p 1200 m, 100 kt); 0.225 / 2.53 (A320 3000 m, 250 kt); 0.503 / 1.30 (B747 3000 m, 250 kt) — JSBSim FGLinearization, independent Jacobian residual ≤ 3.2e-3 | — | **attempted, unvalidated** — against MIL-F-8785C Table IV Cat B (bands unverified here): Level 1 c172p and B747, Level 2 A320 (ζ_sp < 0.30); Dutch roll ζ 0.185 / 0.561 / 0.343 all Level 1; no flight-test referent, so a level describes the model, not the aeroplane (`python -m flightsim.modes`, tests/test_modes.py) |
| A6 | Transport delay | — | — | not applicable |
| A7 | Moist-air density ratio, c172p scene at 1500 m, RH 100 % (T 278.40 K, p 84560.08 Pa, e 887.17 Pa) | S 0.99603420 (JSBSim's density after / before the dew-point write, same FDM, same p and T) − D 0.99603417 (1 − 0.378 e/p) = **+2.9e-8** | 4.0e-6 (u_D = 0.378 × 0.1 % × e/p from A&E 1996, unverified here; u_num 0, a state; u_input 0, stated) | **validated at u_val**, within the 0.05 % criterion. Weak by construction: JSBSim's mixture law and the relation are the same ideal-gas identity with JSBSim's own e on both sides, so this verifies the arithmetic, not the ideal-gas assumption (Gate 3b humidity rung) |
| A8 | JSBSim standard day vs US Standard Atmosphere 1976, ΔT 0 | 0 m: T 0.0 K, p **+0.545 Pa**, ρ +1.0e-5 kg/m³; 3000 m: T +2.0e-4 K, p +0.45 Pa, ρ **+1.08e-5 kg/m³**; 11000 m: T −4.9e-4 K, p −0.034 Pa, ρ +2.9e-6 kg/m³. Worst relative 1.2e-5 | half the table's last digit: T 5e-4 K, p 0.5 Pa, ρ 5e-5 (0 m) / 5e-6 kg/m³ | **within 0.1 %** (criterion met); at u_val 7 of 9 cells validated, the two in bold discrepant at the table's precision (JSBSim's 2116.228 psf is 101325.54 Pa, JSBSIM_CORRECTIONS §25). The table is transcribed from memory [unverified here], checked against the 1976 defining equations within half its last digit |
| A9 | von Kármán σ_w delivered through JSBSim's gust channel, c172p 1500 m, moderate (row 3), 3 s | delivered 2.1739 m/s (std of the channel read back every step) − ladder 2.1889 = **−0.0150 m/s (−0.69 %)** | — (the standard itself, via FGWinds' transcription, unverified here) | **within 10 %**. The Dryden side of "the same σ" is NOT within 10 %: JSBSim's own channel delivers 1.86× the ladder on w over 60 s on Linux (2.13 Windows, 2.60 macOS; P6), so the comparison holds at the commanded ladder only |

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
14. A stated non-standard day keeps the initial TRUE airspeed: 100 kt CAS asked, **95.83 kt CAS flown** at ΔT +30 °C (Gate 3b; open).
15. The dt/2 twin and the three-rate study compared recordings on JSBSim's raw clock, which a piston's crank starts at a rate-dependent time: the observed order read ≈ 0.6 everywhere and the altitude difference was **25×** the integration error (Gate 3b; fixed in core/uncertainty.py).

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
