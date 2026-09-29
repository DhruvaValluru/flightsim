# Verification & Validation Plan

Structure follows MIL-STD-3022's DID: what will be tested, against what
referent, and the pass/fail criteria — all stated **before** the testing.

## 1. Intended use

A research instrument for measuring **aircraft response to environmental
conditions** — terrain-induced wind, turbulence, gusts, boundary-layer shear.
The dependent variables are trajectory, attitude, load factor and control
activity. Visual output is secondary and is not the subject of this plan.

## 2. What is verified vs validated

**Verification** — does the system solve its equations correctly? Testable
entirely in-house, and the bulk of what has been done.

**Validation** — do those equations describe the real world? Requires a
referent. For most quantities here, **no adequate referent exists** (§3.3: stock
JSBSim aircraft carry an explicit no-fidelity disclaimer), and the plan says so
in advance rather than discovering it at reporting time.

## 3. Verification activities and criteria

| # | Activity | Criterion | Where |
|---|---|---|---|
| V1 | Trim equilibrium | mass-held, ≥3 phugoid periods: altitude excursion ≤5 m, CAS ≤2 kt, roll ≤1°, oscillation not growing | Gate 0 |
| V2 | Initial-condition fidelity | every requested IC achieved within 1e-3 relative | Gate 0/1 |
| V3 | Spec reproducibility | identical spec → bit-identical telemetry | Gate 1 |
| V4 | Envelope validation | physically impossible scenarios rejected by named constraint | Gate 1 |
| V5 | Control step response | §6.5 criteria, settling referenced to measured phugoid period | Gate 2 |
| V6 | Loop decoupling | neither channel leaves its own acceptance when both commanded | Gate 2 |
| V7 | Closure | achieved state matches commanded within declared tolerance, or no output | Gate 2 |
| V8 | Environment connectivity | every provider measurably changes the trajectory (null-test ladder) | Gate 3 |
| V9 | Numerical convergence | trajectory difference decreases with timestep refinement | Gate 3 |
| V10 | Terrain round trip | DEM → raster → Landscape → query preserves metres, relief and aspect | Gate 4 |
| V11 | Sweep integrity | interrupted sweep resumes to a case-for-case identical dataset | Gate 7 |
| V12 | Provenance | run reproduces bit-identically from its manifest | Gate 7 |
| V13 | Loading: the hand CG | CG = Σ m·x / Σ m over the XML's empty weight, point masses and tanks equals `inertia/cg-x-in` within 0.1 in on the five configured airframes after the writes and a re-latch; the c172p's XML arms compared with the handbook's | P4, tests/test_loading.py; Gate 3b |
| V14 | Limit monitoring self-trip | a flight beyond a placard speed flags every sample and a cruise flags none; a scripted 4 g pull-up trips n_z; the verifier recomputes the flags | I2, tests/test_limits.py |
| V15 | Failure timing | the write lands at the first step with t ≥ t_s on the run clock; a jam holds the surface within 1e-6 rad over 100 steps; turbine engine-out thrust 0 on the next step; authority 0.5 holds over 100 steps | P3, tests/test_failures.py; Gate 3b |
| V16 | Wake field | V(r_c) = Γ/(4π r_c); the far field vanishes as a dipole; the pair is divergence-free; p_eq of a uniform w is 0 and of w = p·y is p | P7, tests/test_wake.py; Gate 3b |
| V17 | Layered wind | linear in speed and direction between layers, held beyond them; dV/dz per layer; the delivered wind is the interpolation at the aircraft's altitude within 1e-3 m/s | P6, tests/test_shear.py; Gate 3b |
| V18 | Derivation bit-identity | each injection and all four at neutral values bit-identical to the stock airframe over 8 s, per airframe; an absent anchor refused by name | P2, tests/test_derive_injections.py |
| V19 | Atmosphere read-back | `delta-T`, `P-sl-psf`, `dew-point-R` read back before the trim and every step (0, 0, 1e-6 relative); the delivered state equals the transcribed closed form | P1, tests/test_atmosphere.py; Gate 3b |
| V20 | Gust channel | the channel equals the summed providers' contributions and persists only while written (written every step, zero included) | P6, tests/test_gust_provider.py; Gate 3b |

### 3b. Gate 3b: the physics layers' null ladder

`experiments/gate3b_layers.py`. Each rung is one registered variable's null
pair through `core.record_null.run_null_pair` (the identical spec with that
field at its null; the effect per registered channel against its floor;
both digests), 3 s flights. A rung PASSES only when its criterion is met,
its verdict is the expected one and, for a pair expected to reach, the two
output digests differ; a refusal by name is NOT RUN with the name. The
criteria are the blueprint's, stated before the build:

| Rung | Pair | Criterion |
|---|---|---|
| delta-T | c172p, `atmosphere.temperature_deviation_c` +30 vs 0 | TAS / CAS at the first sample within 0.5 % of 1/√σ, σ from P1's closed form, in both runs |
| humidity | c172p, `relative_humidity_pct` 100 vs dry | row A7 |
| vK vs none | c172p, `turbulence_model.intensity` moderate vs unstated | row A9 |
| vK vs Dryden | c172p, `turbulence_model.model` von_karman vs dryden at the same word | the same ladder σ_w commanded to both; the von Kármán side within 10 % (A9); Dryden's channel is JSBSim's own and is not graded |
| encounter | c172p behind a B747 (250 kt, 20 s old, 25.315 m right, 15 m above) vs none | peak \|roll(with) − roll(without)\| > 5° |
| far control | the same generator 300 m to the side vs none | SILENT over the graded channels |
| icing | c172p, `icing.eta` 0.2 vs 0 | lift at fixed α falls by 1 + η k_lift within 1 % |
| loading | c172p, 136 kg at the aft-most seat vs unstated | the CG, the trim elevator and the pitch each past its floor |
| engine-out | A320 open loop, engine 0 at 1 s vs none | thrust < 1 N on every sample after the write, > 1 kN without |
| jam | A320 under TECS in moderate Dryden (one seed), elevator at 1 s vs none | the jam holds within 1e-6 rad over 100 steps |
| layered | c172p, `wind_profile.kind` layered vs uniform (20 kt from 270) | the delivered wind equals the layers' interpolation within 1e-3 m/s |

`experiments/gate3b_convergence.py` extends V9: the committed c172p example
(turbulence off) at 60 / 120 / 240 Hz gives Richardson's observed order per
SRQ, written to `data/convergence/gate3b_convergence.json`, which u_num
reads for that case (the order capped at the integrators' formal order 1).

## 4. Validation activities and referents

| # | Quantity | Referent | u_D basis | Expected outcome |
|---|---|---|---|---|
| A1 | Clean 1g stall speed | published performance figure, open literature | wide: a specification number, not a measurement | validated at u_val, or discrepant |
| A2 | Turbulence σ_w vs W20 | MIL-F-8785C low-altitude relation σ_w = 0.1·W20 | the standard itself | validated |
| A3 | Takeoff ground roll | **none available** | — | inconclusive |
| A4 | Engine spool time | **none available** | — | inconclusive |
| A5 | Short-period / Dutch-roll damping | MIL-F-8785C Level 1 bands (encoded, unverified here) | — | attempted: linearised with JSBSim's FGLinearization about the trimmed state, graded per class and category; unvalidated for want of a flight-test referent |
| A6 | Transport delay | 14 CFR Part 60 ≤150 ms | — | not applicable: interactive host does not build |
| A7 | Moist-air density ratio ρ_humid / ρ_dry at the same p and T | the ideal-gas mixture relation 1 − 0.378 e/p | A&E 1996's ~0.1 % difference in e_s: u_D = 0.378 × 0.001 × e/p | within 0.05 %; validated at u_val when \|E\| ≤ u_D |
| A8 | Standard-day T, p, ρ at 0 / 3000 / 11000 m, ΔT = 0 | US Standard Atmosphere 1976 table (transcribed, unverified here; checked against the 1976 defining equations) | half a unit in the table's last printed digit | within 0.1 %; at u_val per cell |
| A9 | von Kármán σ_w delivered through JSBSim | MIL-F-8785C's ladder as FGWinds transcribes it (unverified here) | — (the standard itself, as A2) | within 10 % |

Reporting form is ASME V&V 20: comparison error `E = S − D` against validation
uncertainty `u_val = √(u_D² + u_num² + u_input²)`. **A comparison where |E| <
u_val is reported as validated *at the level of u_val*, not as "correct".**

## 5. Acceptance threshold

NASA-STD-7009A credibility level **2** on every factor scored, declared in
advance. Level 3+ requires independent review, which nothing here has had.

## 6. Known exclusions

* Rendering (Phases 5–6) is not covered: it does not build on the current
  toolchain, and Movie Render Queue is not bit-deterministic in any case.
* No EO/IR sensor modelling exists, so nothing about sensor fidelity is claimed.
* Gain and phase margins (§6.5: ≥6 dB, ≥45°) are **unverified**.
