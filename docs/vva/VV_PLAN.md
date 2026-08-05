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

## 4. Validation activities and referents

| # | Quantity | Referent | u_D basis | Expected outcome |
|---|---|---|---|---|
| A1 | Clean 1g stall speed | published performance figure, open literature | wide: a specification number, not a measurement | validated at u_val, or discrepant |
| A2 | Turbulence σ_w vs W20 | MIL-F-8785C low-altitude relation σ_w = 0.1·W20 | the standard itself | validated |
| A3 | Takeoff ground roll | **none available** | — | inconclusive |
| A4 | Engine spool time | **none available** | — | inconclusive |
| A5 | Short-period / Dutch-roll damping | MIL-F-8785C Level 1 bands | — | **not attempted**: requires linearisation this build does not perform |
| A6 | Transport delay | 14 CFR Part 60 ≤150 ms | — | not applicable: interactive host does not build |

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
