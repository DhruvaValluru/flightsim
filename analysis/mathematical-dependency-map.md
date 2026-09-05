# Mathematical dependency map — the aircraft in the air

Every arrow below was traced to a line of code or measured by running the
physics; the legend says which. "JSBSim" means the coupling lives inside
the flight-dynamics library and the repository consumes its result
without re-deriving it — which is the correct place for it.

Legend: `──▶` verified coupling · `╌╌▶` present but severed on one host ·
`✗` absent · `[m]` measured in this audit · `[c]` traced in code.

## 1. The actual state-propagation pipeline (one tick, 1/120 s)

```
spec (validated, provenanced)
  │  configure_from_spec: ICs in _IC_PRIORITY order ─▶ run_ic ─▶ start_engines ─▶ trim
  │                                                      ▲
  │                          wind written here is ZEROED by trim (FGTrim::Initialize)   [m]
  ▼
EnvironmentStack.apply(fdm)                                                       [c]
  ├─ Σ WindProvider.wind_at(pos,t) ─▶ atmosphere/wind-{north,east,down}-fps
  │     steady · log-profile · orographic(w=U·∇h, lee sink) · rotor W20 · thermals · downburst · tornado
  └─ TurbulenceProvider.step_writes ─▶ atmosphere/turb W20 (Dryden lives inside JSBSim)
TerrainGround.apply(fdm) ─▶ position/terrain-elevation-asl-ft                     [c]
fdm.step()  ═══ JSBSim ═══════════════════════════════════════════════════════════
  │  V_air = V_ground − V_wind ─▶ α, β, q̄ ─▶ C_L(α,…) C_D C_m … (aircraft XML tables)
  │  forces (aero, thrust, gravity, ground reaction) ─▶ a = ΣF/m ─▶ v ─▶ x   (AB2 / AB3)
  │  moments ─▶ ω̇ = I⁻¹(M − ω×Iω) ─▶ ω ─▶ quaternion (rect. Euler, normalised)
  │  fuel flow ─▶ m(t)   (unless hold_mass)
  │  FCS: tecs.xml runs HERE at 120 Hz: setpoints ─▶ throttle/elevator/aileron/rudder
  ▼
AirframeContact.check(state)  span stations vs raster ─▶ raise on impact        [c]
autopilot.update()  every 60 steps: CAS demand ─▶ TAS setpoint (ρ-corrected)     [c]
recorder.sample()   every 0.1 s of FDM time                                      [c]
```

There is exactly one writer of physical state: `fdm.step()`. Everything
else writes inputs (wind, terrain elevation, setpoints) or reads.

## 2. Quantities: origin → owner → consumers

| quantity | originates in | authoritative owner | consumed by | status |
|---|---|---|---|---|
| position (lat, lon, h) | JSBSim propagate | JSBSim | recorder, contact, environment position, capture, render | ──▶ |
| velocity (u,v,w / NED) | JSBSim | JSBSim | TECS (V̇ from body accelerations), recorder | ──▶ |
| attitude (quaternion) | JSBSim | JSBSim | TECS (φ, θ), capture, render | ──▶ |
| angular rates p,q,r | JSBSim | JSBSim | TECS inner loops, yaw damper | ──▶ |
| α, β | JSBSim from V_air | JSBSim | aero tables; **not** consumed by any control law (β unused) | ──▶ / ✗ β→rudder |
| ρ, T, P | JSBSim ISA at h | JSBSim | q̄, engine model, CAS↔TAS in autopilot | ──▶ (no deviations: ✗ provider) |
| mass, fuel | JSBSim propulsion | JSBSim | a = ΣF/m | ──▶ headless · ╌╌▶ render (held) |
| thrust | JSBSim engines from throttle | JSBSim | ΣF | ──▶ |
| lift, drag | JSBSim aero | JSBSim | ΣF; recorder (fw*) | ──▶ |
| wind vector | providers | EnvironmentStack | JSBSim V_air | ──▶ in loop · ✗ at trim |
| turbulence | JSBSim Dryden (seeded) | JSBSim | V_air | ──▶ in run · ✗ in clearance plan |
| terrain elevation under a/c | raster | TerrainGround / UEGroundCallback | JSBSim AGL, ground reactions, contact | ──▶ |
| terrain elevation AHEAD | raster (lookup exists) | — | **nothing** | ✗ |
| max climb / min sink capability | — | — | **nothing** (TECS needs it, look-ahead needs it) | ✗ |
| altitude / TAS / heading setpoints | Autopilot.command | Autopilot | TECS | ──▶ headless · ✗ render host (no TECS) |
| bank limit 25°, ḣ limit, V̇ limit | tecs.xml constants | TECS | TECS | ──▶ (not performance-derived) |
| control surfaces | TECS / script deltas | JSBSim FCS | moments | ──▶ |
| waypoints / route / cross-track | — | — | — | ✗ |

## 3. Causal chains, as they actually resolve

```
TURN        ap/heading-setpoint ─▶ err (wrapped) ─▶ ×1.2 ─▶ φ_dem (≤25°) ─▶ ×3.5 ─▶ p_dem ─▶ PID ─▶ aileron
            ─▶ JSBSim roll ─▶ lift tilts ─▶ a_lat ─▶ ψ̇                                 [m] n_z=1/cosφ ±0.15%
            washout(r) ─▶ rudder (damper only)  ⇒  steady β≈1°, Y/W=−3.6%, ψ̇ 9% below g·tanφ/V   [m]

CLIMB       ap/altitude-setpoint ─▶ ḣ_dem=(h_dem−h)/τ (≤40 ft/s) ─▶ Ė_err/(gV) ─▶ ×1.2 ─▶ throttle
            ─▶ thrust>drag ─▶ Ė>0 ; pitch loop redistributes ─▶ γ↑ at const α, const V     [m]
            fixed gain ⇒ 54% of excess power used, 75 s for 300 m; no T/W scaling         [m]

SPEED       CAS demand ─▶ (TAS/CAS measured) ─▶ TAS setpoint ─▶ same energy loop           [c]

WIND        provider ─▶ wind props ─▶ V_air ─▶ α,β,q̄ ─▶ forces ⇒ crab, GS≠TAS emerge        [m]
            BUT trim sees wind=0 ⇒ step at t=0 ⇒ open-loop ±330 m / 30 s                   [m]

TERRAIN     raster ─▶ elevation under a/c ─▶ AGL, contact  ✓
            raster ─▶ ahead ─▶ required climb ─▶ capability ─▶ setpoint   ✗ (no consumer)

MASS        fuel burn ─▶ m ─▶ a  ✓ headless (+89.6 m / 400 s, repo-measured) · held on render host
```

## 4. Ideal graph (additive over §1)

```
                 PERFORMANCE MODEL (new, measured from the FDM like the lift curve)
                 Ė_max(m,ρ,V), Ė_min, φ_max(n_z), γ_max
                        │                    │
                        ▼                    ▼
   TECS throttle normalisation        TERRAIN LOOK-AHEAD (new consumer)
   (airframe-invariant bandwidth)     raster along projected track, t..t+T
                                       ─▶ required Ė ─▶ feasible? ─▶ ḣ setpoint ramp / named refusal
                                                                          │
   TRIM IN WIND (fixed point on observed vc, β)  ─▶ no t=0 step            ▼
   β (or a_y) ─▶ rudder (turn coordination)      ─▶ ψ̇ = g·tanφ/V     Autopilot.command(altitude_m)
   [optional] waypoints ─▶ L1: a_lat = 4ζ²·V²/L1·sin η ─▶ φ_dem       (interface already exists)
   render host: TECS present, or paired headless run asserted
```

Nothing in §4 replaces a physics path. Every addition either feeds an
input JSBSim already consumes, or reads an output it already produces.
